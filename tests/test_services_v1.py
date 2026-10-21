import io
import json
import os
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from services.image_processor import (
    ImageProcessingError, MAX_RAW_BYTES, process_image, smart_file_reuse,
)
from services.llm_gateway import (
    ExtractionResult, GatewayError, LLMGatewayService, SIMULATION_VALUES,
)


def image_bytes(format="PNG", size=(180, 120)):
    buffer = io.BytesIO()
    Image.new("RGBA" if format == "PNG" else "RGB", size, "white").save(buffer, format)
    return buffer.getvalue()


def completion(slots, *, finish="stop", **message):
    return httpx.Response(200, json={"choices": [{
        "finish_reason": finish,
        "message": {"content": json.dumps({"slots": slots}), **message},
    }]})


class ImageProcessorTests(unittest.TestCase):
    def test_compression_strips_metadata_and_unsafe_filename(self):
        image = Image.new("RGB", (400, 300), "white")
        exif = Image.Exif()
        exif[270] = "private identity metadata"
        exif[274] = 6
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", exif=exif)
        result = process_image(buffer.getvalue(), "../../secret.jpg", "image/jpeg")
        self.assertLess(result.size, 900_000)
        self.assertEqual(result.size, len(result.data))
        self.assertEqual(result.mime_type, "image/jpeg")
        self.assertNotIn("secret", result.filename)
        self.assertEqual(len(result.sha256), 64)
        with Image.open(io.BytesIO(result.data)) as output:
            self.assertEqual(output.size, (300, 400))
            self.assertFalse(output.getexif())

    def test_noise_is_compressed_without_upscaling(self):
        noise = Image.effect_noise((2000, 1600), 80).convert("RGB")
        buffer = io.BytesIO()
        noise.save(buffer, "PNG")
        result = process_image(buffer.getvalue(), "proof.png", "image/png")
        self.assertLess(result.size, 900_000)
        with Image.open(io.BytesIO(result.data)) as output:
            self.assertLessEqual(output.width, 2000)
            self.assertGreaterEqual(output.width, 640)

    def test_invalid_and_mismatched_bytes_rejected(self):
        for raw, mime in ((b"<script>alert(1)</script>", "image/png"), (image_bytes(), "image/jpeg"), (b"%PDF-1.7", "application/pdf"), (b"", "image/png"), (b"x" * (MAX_RAW_BYTES + 1), "image/png")):
            with self.subTest(mime=mime, size=len(raw)), self.assertRaises(ImageProcessingError):
                process_image(raw, "proof.png", mime)

    def test_resolution_guard_and_animated_images(self):
        with patch("services.image_processor.MAX_PIXELS", 100), self.assertRaises(ImageProcessingError):
            process_image(image_bytes(), "proof.png", "image/png")
        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(buffer, "PNG", save_all=True, append_images=[Image.new("RGB", (20, 20), "black")])
        with self.assertRaises(ImageProcessingError):
            process_image(buffer.getvalue(), "proof.png", "image/png")

    def test_chat_evidence_pointer_reused_three_times(self):
        metadata = {"file_id": "one-stored-file"}
        refs = smart_file_reuse("bukti_chat", metadata)
        self.assertEqual(len(refs), 3)
        self.assertTrue(all(value is metadata for value in refs.values()))
        with self.assertRaises(ValueError):
            smart_file_reuse("unknown", metadata)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "AI_MODE": "auto", "AI_API_KEY": "", "AI_BASE_URL": "http://localhost:8000/v1",
            "VISION_MODEL_NAME": "vision-test", "CHAT_MODEL_NAME": "chat-test",
            "AI_RESPONSE_FORMAT": "json_schema", "AI_TIMEOUT_SECONDS": "10",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_simulation_is_explicit_and_uses_valid_schema(self):
        gateway = LLMGatewayService()
        for kind, expected in SIMULATION_VALUES.items():
            result = await gateway.extract(kind, image_bytes(), "image/png")
            self.assertTrue(result.simulated)
            self.assertEqual(result.values, expected)
            self.assertEqual(result.confidence.keys(), result.values.keys())

    async def test_simulation_chat_only_fills_allowed_fields(self):
        gateway = LLMGatewayService()
        slots = ["tahap1.nomor_telepon_pelapor", "tahap1.email_pelapor"]
        result = await gateway.extract_chat("nomor hp=800000000000\nemail=pelapor.dummy@example.com", slots, {})
        self.assertEqual(result.values[slots[0]], "800000000000")
        self.assertEqual(result.values[slots[1]], "pelapor.dummy@example.com")
        with self.assertRaises(GatewayError):
            await gateway.extract_chat("email=pelapor.dummy@example.com\nsubmit=true", slots, {})
        with self.assertRaises(GatewayError):
            await gateway.extract_chat("not-email", ["tahap1.email_pelapor"], {})

    async def test_remote_structured_extraction_and_environment_models(self):
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(body["response_format"]["type"], "json_schema")
            return completion([{"field": "tahap1.nama_pelapor", "value": "PELAPOR DUMMY", "confidence": 0.9}])

        os.environ["AI_MODE"] = "remote"
        gateway = LLMGatewayService(transport=httpx.MockTransport(handler))
        result = await gateway.extract("ktp", image_bytes(), "image/png")
        self.assertFalse(result.simulated)
        self.assertEqual(requests[0]["model"], "vision-test")
        self.assertEqual(result.confidence["tahap1.nama_pelapor"], 0.9)

    async def test_remote_chat_requests_only_delta_and_supports_json_object(self):
        slot = "tahap1.email_pelapor"

        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(body["model"], "chat-test")
            self.assertEqual(body["response_format"], {"type": "json_object"})
            self.assertNotIn("secret", body["messages"][1]["content"])
            return completion([{"field": slot, "value": "pelapor.dummy@example.com", "confidence": 1.0}])

        os.environ.update(AI_MODE="remote", AI_RESPONSE_FORMAT="json_object")
        result = await LLMGatewayService(transport=httpx.MockTransport(handler)).extract_chat("pelapor.dummy@example.com", [slot], {"api_key": "secret"})
        self.assertEqual(result.values[slot], "pelapor.dummy@example.com")

    async def test_provider_cannot_change_action_fields_or_confidence(self):
        os.environ["AI_MODE"] = "remote"
        examples = [
            [{"field": "tahap5.setuju_syarat_dan_ketentuan", "value": "true", "confidence": 1.0}],
            [{"field": "tahap1.nama_pelapor", "value": "DUMMY", "confidence": 1.1}],
            [{"field": "tahap1.nama_pelapor", "value": "DUMMY", "confidence": -0.1}],
            [{"field": "tahap1.nama_pelapor", "value": "DUMMY", "confidence": True}],
            [{"field": "tahap1.nama_pelapor", "value": {"execute": "submit"}, "confidence": 0.9}],
            [{"field": "tahap1.nama_pelapor", "value": "DUMMY", "confidence": 0.9}] * 2,
        ]
        for slots in examples:
            with self.subTest(slots=slots), self.assertRaises(GatewayError):
                await LLMGatewayService(transport=httpx.MockTransport(lambda request: completion(slots))).extract("ktp", image_bytes(), "image/png")

    async def test_partial_refusal_and_network_failure_never_generate_dummy(self):
        os.environ["AI_MODE"] = "remote"
        transports = [
            httpx.MockTransport(lambda request: completion([], finish="length")),
            httpx.MockTransport(lambda request: completion([], refusal="cannot extract")),
            httpx.MockTransport(lambda request: httpx.Response(401, text="private provider body")),
            httpx.MockTransport(lambda request: httpx.Response(200, text="not JSON")),
        ]
        for transport in transports:
            with self.subTest(transport=transport), self.assertRaises(GatewayError) as caught:
                await LLMGatewayService(transport=transport).extract("ktp", image_bytes(), "image/png")
            self.assertNotIn("private", str(caught.exception))

        def timeout(request):
            raise httpx.ReadTimeout("sensitive server detail", request=request)

        with self.assertRaises(GatewayError) as caught:
            await LLMGatewayService(transport=httpx.MockTransport(timeout)).extract("ktp", image_bytes(), "image/png")
        self.assertIn("tidak diganti", str(caught.exception))
        self.assertNotIn("sensitive", str(caught.exception))

    def test_insecure_remote_and_invalid_mode_rejected(self):
        for values in ({"AI_MODE": "invalid"}, {"AI_MODE": "remote", "AI_BASE_URL": "http://example.com/v1"}, {"AI_MODE": "remote", "AI_BASE_URL": "https://example.com/v1", "AI_API_KEY": ""}):
            with self.subTest(values=values), patch.dict(os.environ, values), self.assertRaises(GatewayError):
                LLMGatewayService()

    def test_result_requires_known_values_and_bounded_confidence(self):
        with self.assertRaises(ValueError):
            ExtractionResult(values={"tahap1.nama_pelapor": "DUMMY"}, confidence={})
        with self.assertRaises(ValueError):
            ExtractionResult(values={"tahap1.nama_pelapor": "DUMMY"}, confidence={"tahap1.nama_pelapor": float("nan")})


if __name__ == "__main__":
    unittest.main()
