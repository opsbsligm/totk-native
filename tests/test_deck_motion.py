"""Check exact report framing, signed values and the Switch sensor coordinate frame."""
import ctypes
from pathlib import Path
import struct
import platform
import sys
import subprocess
import tempfile
import unittest

class DeckMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='deck-motion-',dir=Path.cwd())
        cls.addClassCleanup(cls.tmp.cleanup)
        source=Path(__file__).resolve().parents[1]/'src/host/deck_motion_decode.c'
        lib=Path(cls.tmp.name)/'decode.so'
        arch=['-arch',platform.machine()] if sys.platform == 'darwin' else []
        subprocess.run(['cc','-std=c11','-shared','-fPIC',*arch,str(source),'-o',str(lib)],check=True)
        if sys.platform.startswith('linux'):
            reader=source.with_name('deck_motion_linux.c')
            subprocess.run(['cc','-std=gnu17','-Wall','-Wextra','-Werror','-c',str(reader),'-o',str(Path(cls.tmp.name)/'reader.o')],check=True)
        cls.lib=ctypes.CDLL(str(lib))
        cls.decode=cls.lib.nd_deck_motion_decode
        cls.decode.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_uint32),
                             ctypes.POINTER(ctypes.c_double),ctypes.POINTER(ctypes.c_double)]
        cls.decode.restype=ctypes.c_int
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def packet(self,acc=(0,0,16384),gyro=(0,0,0),sequence=123):
        p=bytearray(64);p[:4]=bytes([1,0,9,64]);struct.pack_into('<I',p,4,sequence)
        struct.pack_into('<hhh',p,24,*acc);struct.pack_into('<hhh',p,30,*gyro);return p
    def run_decode(self,p):
        raw=ctypes.create_string_buffer(bytes(p));seq=ctypes.c_uint32()
        acc=(ctypes.c_double*3)();gyro=(ctypes.c_double*3)()
        ok=self.decode(raw,len(p),ctypes.byref(seq),acc,gyro)
        return ok,seq.value,list(acc),list(gyro)
    def test_face_up_gravity_and_packet_wrap(self):
        ok,seq,acc,gyro=self.run_decode(self.packet(sequence=0xffffffff))
        self.assertEqual(ok,1);self.assertEqual(seq,0xffffffff)
        self.assertEqual(acc,[0,0,-1]);self.assertEqual(gyro,[0,0,0])
    def test_signed_axes_and_units_match_composed_sdl_rotation(self):
        ok,_,acc,gyro=self.run_decode(self.packet(acc=(16384,-16384,0),gyro=(16384,-16384,-32768)))
        self.assertEqual(ok,1);self.assertEqual(acc,[-1,1,0])
        import math
        self.assertAlmostEqual(gyro[0],1000*math.pi/180)
        self.assertAlmostEqual(gyro[1],-1000*math.pi/180)
        self.assertAlmostEqual(gyro[2],-2000*math.pi/180)
    def test_refuses_truncated_and_other_report_types(self):
        original=self.packet()
        for size in [0,1,4,24,30,63,65,128]:
            with self.subTest(size=size):self.assertEqual(self.run_decode((original*2)[:size])[0],0)
        for offset in range(4):
            p=bytearray(original);p[offset]^=1
            with self.subTest(offset=offset):self.assertEqual(self.run_decode(p)[0],0)
    def test_disabled_imu_is_not_a_live_sensor(self):
        self.assertEqual(self.run_decode(self.packet(acc=(0,0,0)))[0],0)
    def test_buttons_are_ignored(self):
        p=self.packet();expected=self.run_decode(p)
        p[8:24]=b'\xff'*16;p[36:64]=b'\xff'*28
        self.assertEqual(self.run_decode(p),expected)

if __name__=='__main__':unittest.main()
