import io
import json
import os
from pathlib import Path
import shutil
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from fastapi import HTTPException
from PIL import Image

import app


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AI_MODE": "local"})
        self.env.start()
        app.SESSIONS.clear()
        self.client = TestClient(app.app)
        self.token = self.client.post('/api/sessions').json()['session_id']
        self.url = '/api/sessions/' + self.token

    def tearDown(self):
        self.env.stop()

    def edit(self, values):
        return self.client.patch(self.url, json={"values": values})

    def complete(self):
        values = {row[0]: row[5] for row in app.FIELDS}
        response = self.edit(values)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_draft_requires_complete_data_and_review_and_never_submits(self):
        self.assertEqual(self.client.post(self.url + '/draft', json={'reviewed': True}).status_code, 422)
        self.assertEqual(self.complete()['missing'], [])
        self.assertEqual(self.client.post(self.url + '/draft', json={'reviewed': False}).status_code, 422)
        export = self.client.post(self.url + '/draft', json={'reviewed': True})
        self.assertEqual(export.status_code, 200)
        self.assertFalse(export.json()['submitted'])
        self.assertFalse(export.json()['identity_verified'])
        self.assertEqual(export.json()['mode'], 'DRAFT_ONLY')
        self.assertEqual(self.client.post('/api/submit', json={}).status_code, 404)
        self.assertFalse(self.client.get('/api/config').json()['submission_enabled'])

    def test_invalid_edit_is_atomic_and_identifiers_keep_leading_zeroes(self):
        self.edit({'rekening_penerima': '0000000001'})
        result = self.edit({'rekening_penerima': 'wrong', 'pelapor_nama': 'CHANGED'})
        self.assertEqual(result.status_code, 422)
        data = self.client.get(self.url).json()['data']
        self.assertEqual(data['rekening_penerima'], '0000000001')
        self.assertIsNone(data['pelapor_nama'])
        self.assertEqual(self.edit({'not_a_field': 'value'}).status_code, 422)
        self.assertEqual(self.edit({'nominal': True}).status_code, 422)
        self.assertEqual(self.edit({'nominal': 0}).status_code, 422)
        self.assertEqual(self.edit({'nominal': '1,5'}).status_code, 422)
        self.assertEqual(self.edit({'nominal': 'Rp1.250.000,00'}).json()['data']['nominal'], 1250000)
        self.assertEqual(self.edit({'waktu_transaksi': '2026-10-19'}).status_code, 422)
        self.assertEqual(self.edit({'waktu_transaksi': '2099-01-01T10:00'}).status_code, 422)
        self.assertEqual(self.edit({'waktu_transaksi': '2026-10-19T03:00:00Z'}).json()['data']['waktu_transaksi'], '2026-10-19T10:00:00+07:00')

    def test_chat_fills_only_the_next_required_slot(self):
        result = self.client.post(self.url + '/messages', json={'text': 'PELAPOR DUMMY'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['pelapor_nama'], 'PELAPOR DUMMY')
        self.assertEqual(result.json()['missing'][0], 'pelapor_email')
        bad = self.client.post(self.url + '/messages', json={'text': 'not an email'})
        self.assertEqual(bad.status_code, 422)
        self.assertIsNone(self.client.get(self.url).json()['data']['pelapor_email'])

    def test_untrusted_upload_type_size_and_content_are_rejected(self):
        for body, mime, status in [(b'hello','application/pdf',415), (b'<script>bad</script>','image/png',422), (b'x' * (app.MAX_UPLOAD + 1),'image/png',413)]:
            result = self.client.post(self.url + '/evidence', content=body, headers={'Content-Type':mime})
            self.assertEqual(result.status_code, status, result.text)

    def test_decompression_size_guard(self):
        buffer = io.BytesIO()
        Image.new('RGB',(100,100)).save(buffer,'PNG')
        with patch.object(Image, 'MAX_IMAGE_PIXELS', 2000):
            with self.assertRaises(HTTPException):
                app.image_png(buffer.getvalue())

    @unittest.skipUnless(shutil.which('tesseract'), 'Tesseract not installed')
    def test_real_dummy_ocr_and_chat_flow(self):
        path = Path(__file__).resolve().parent.parent / 'fixtures'
        # Manual corrections take precedence over later OCR, even with conflicting evidence.
        self.edit({'rekening_penerima':'0000000002'})
        result = self.client.post(self.url + '/evidence', content=(path/'bukti-dummy.png').read_bytes(), headers={'Content-Type':'image/png'})
        self.assertEqual(result.status_code,200,result.text)
        data = result.json()['data']
        expected = json.loads((path/'expected.json').read_text())
        for key,value in expected.items():
            self.assertEqual(data[key], '0000000002' if key == 'rekening_penerima' else value)
        self.assertEqual(result.json()['sources']['rekening_penerima'], 'manual')
        while result.json()['missing']:
            key = result.json()['missing'][0]
            result = self.client.post(self.url + '/messages', json={'text':app.FIELD_MAP[key][5]})
            self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.post(self.url+'/draft',json={'reviewed':True}).status_code,200)

    def test_sessions_are_isolated_expire_and_delete(self):
        second = self.client.post('/api/sessions').json()['session_id']
        self.edit({'pelapor_nama':'DUMMY'})
        self.assertIsNone(self.client.get('/api/sessions/'+second).json()['data']['pelapor_nama'])
        app.SESSIONS[self.token]['touched'] = time.monotonic() - app.SESSION_TTL - 1
        self.assertEqual(self.client.get(self.url).status_code,404)
        self.assertEqual(self.client.delete('/api/sessions/'+second).status_code,204)
        self.assertEqual(self.client.get('/api/sessions/'+second).status_code,404)

    def test_gateway_failure_does_not_change_the_draft(self):
        before = self.edit({row[0]: row[5] for row in app.FIELDS if row[2] in (1, 2)}).json()['data']
        with patch.dict(os.environ, {'AI_MODE':'remote'}), patch.object(app, 'gateway_extract', new=AsyncMock(side_effect=HTTPException(502,'Gateway gagal'))):
            result = self.client.post(self.url+'/messages',json={'text':'Belanja online'})
        self.assertEqual(result.status_code,502)
        self.assertEqual(self.client.get(self.url).json()['data'], before)

    def test_gateway_validates_output_and_never_calls_tools(self):
        self.edit({row[0]: row[5] for row in app.FIELDS if row[2] in (1, 2)})
        with patch.dict(os.environ, {'AI_MODE':'remote','AI_BASE_URL':'http://127.0.0.1:9999/v1','AI_MODEL':'test-model'}):
            for content,expected_status in [('{"kategori_modus":"BELANJA_ONLINE"}',200), ('{"pelapor_nik":"bad"}',502), ('{"tool_call":"submit"}',502), ('not json',502)]:
                response = httpx_response(content)
                client = AsyncMock()
                client.post.return_value = response
                manager = AsyncMock()
                manager.__aenter__.return_value = client
                with patch.object(app.httpx, 'AsyncClient', return_value=manager):
                    result = self.client.post(self.url+'/messages',json={'text':'Pelapor dummy'})
                self.assertEqual(result.status_code,expected_status,result.text)
                sent = client.post.call_args.kwargs['json']
                self.assertNotIn('tools',sent)

    def test_local_mode_does_not_contact_a_provider_and_pages_load(self):
        with patch.object(app.httpx, 'AsyncClient', side_effect=AssertionError('No external AI allowed')):
            self.assertEqual(self.client.post(self.url+'/messages',json={'text':'DUMMY'}).status_code,200)
        for path in ['/','/assistant','/Guest','/Guest/LaporanV2','/Guest/CekLaporan','/widget','/integration','/docs','/openapi.json','/static/widget.js']:
            result = self.client.get(path)
            self.assertEqual(result.status_code,200,path)
            self.assertEqual(result.headers['cache-control'],'no-store')
        for path in ['/assistant', '/widget']:
            self.assertEqual(str(self.client.get(path).url).split('testserver')[-1], '/Guest/LaporanV2?assistant=1')


def httpx_response(content):
    import httpx
    return httpx.Response(200,request=httpx.Request('POST','http://127.0.0.1:9999/v1/chat/completions'),json={'choices':[{'message':{'content':content}}]})


if __name__ == '__main__':
    unittest.main()
