# SPDX-License-Identifier: Apache-2.0
# Mesh test vectors: Nordic Semiconductor Android nRF Mesh Library; see NOTICE.
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
import importlib
from types import ModuleType
pkg=ModuleType('mesh_vectors');pkg.__path__=[str(ROOT/'custom_components/mspa_local')]
sys.modules['mesh_vectors']=pkg
t=importlib.import_module('mesh_vectors.transport')


class TransportTests(unittest.TestCase):
    def test_segmented_reply_standard_vector(self):
        a=t.AccessAssembler()
        base={'source':3,'destination':0x1201,'ctl':False,'ttl':5}
        self.assertIsNone(a.feed(base|{'sequence':0x3129ac,
            'payload':bytes.fromhex('8026ac21cfdc18c52fdef772e0e17308')}))
        result=a.feed(base|{'sequence':0x3129ab,
            'payload':bytes.fromhex('8026ac01ee9dddfd2169326d23f3afdf')})
        self.assertEqual(result['sequence'],0x3129ab)
        self.assertEqual(result['encrypted'].hex(),'ee9dddfd2169326d23f3afdfcfdc18c52fdef772e0e17308')
        self.assertEqual(result['ack'].hex(),'0026ac00000003')
        self.assertFalse(result['akf'])

    def test_k4_and_upper_transport_standard_vectors(self):
        key=bytes.fromhex('3216d1509884b533248541792b877f98')
        self.assertEqual(t.k4(key),0x38)
        key=bytes.fromhex('9d6dd0e96eb25dc19a40ed9914f8f03f')
        encrypted=t.upper_encrypt(key,0x12345678,6,0x1201,3,
                                  bytes.fromhex('800300563412'),device_key=True)
        self.assertEqual(encrypted.hex(),'89511bf1d1a81c11dcef')

    def test_k2_standard_vector(self):
        nid,enc,privacy=t.k2(bytes.fromhex('f7a2a44f8e8a8029064f173ddc1e2b00'))
        self.assertEqual(nid,0x7f)
        self.assertEqual(enc.hex(),'9f589181a0f50de73c8070c7a6d27f46')
        self.assertEqual(privacy.hex(),'4c715bd4a64b938f99b453351653124f')

    def test_published_network_vector(self):
        key=bytes.fromhex('7dd7364cd842ad18c17c2b820c84c3d6')
        payload=bytes.fromhex('0089511bf1d1a81c11dcef')
        packet=t.encode_network(key,0x12345678,6,0x1201,3,payload,ttl=11)
        self.assertEqual(packet.hex(),'68e80e5da5af0e6b9be7f5a642f2f98680e61c3a8b47f228')
        decoded=t.decode_network(key,0x12345678,packet)
        self.assertEqual(decoded['payload'],payload)
        self.assertEqual(decoded['source'],0x1201)
        self.assertEqual(decoded['sequence'],6)

    def test_proxy_round_trip_and_tampering(self):
        key=bytes.fromhex('7dd7364cd842ad18c17c2b820c84c3d6')
        packet=t.encode_network(key,0,1,0x7ffe,0,b'\0\0',proxy=True,ctl=True)
        self.assertEqual(t.decode_network(key,0,packet,proxy=True)['payload'],b'\0\0')
        self.assertIsNone(t.decode_network(key,1,packet,proxy=True))
        for i in range(len(packet)):
            damaged=bytearray(packet); damaged[i]^=1
            self.assertIsNone(t.decode_network(key,0,bytes(damaged),proxy=True))
        self.assertIsNone(t.decode_network(bytes(16),0,packet,proxy=True))


if __name__=='__main__':unittest.main(verbosity=2)
