"""Run python test_ssl_v31.py ; network-free verification."""
import sys, types, unittest
from unittest.mock import patch
from importlib.util import spec_from_file_location,module_from_spec
from pathlib import Path
spec=spec_from_file_location('jra_pdf_ssl',Path(__file__).with_name('31_jra_rpdf.py'))
m=module_from_spec(spec);spec.loader.exec_module(m)

class Reply:
 def geturl(self):return 'https://www.jra.go.jp/keiba/rpdf/pdf/20261107-05tokyo01.pdf'
 def read(self,n):return b'%PDF-1.7\nFAKE'
 def __enter__(self):return self
 def __exit__(self,*args):return False

class Robots:
 called=False
 def set_url(self,url): self.url=url
 def read(self):
  self.called=True
  if not fake_trust.calls:raise AssertionError('truststore injection must precede robots.read')
 def mtime(self):return 123
 def can_fetch(self,ua,url):return True

fake_trust=types.SimpleNamespace(calls=0)
def inject(): fake_trust.calls+=1
fake_trust.inject_into_ssl=inject
class Test(unittest.TestCase):
 def test_truststore_used_for_robots_and_pdf(self):
  fake_trust.calls=0
  with patch.dict(sys.modules,{'truststore':fake_trust}),patch.object(m,'RobotFileParser',Robots),patch.object(m,'urlopen',return_value=Reply()):
   data=m._read_url('https://www.jra.go.jp/keiba/rpdf/pdf/20261107-05tokyo01.pdf')
  self.assertTrue(data.startswith(b'%PDF-'));self.assertEqual(fake_trust.calls,1)
 def test_robot_disallow_stops_before_pdf(self):
  class Deny(Robots):
   def can_fetch(self,ua,url):return False
  fake_trust.calls=0
  with patch.dict(sys.modules,{'truststore':fake_trust}),patch.object(m,'RobotFileParser',Deny),patch.object(m,'urlopen') as download:
   with self.assertRaisesRegex(m.IntakeError,'許可されていません'):
    m._read_url('https://www.jra.go.jp/keiba/rpdf/pdf/20261107-05tokyo01.pdf')
   download.assert_not_called()
 def test_robot_unverifiable_stops(self):
  class Missing(Robots):
   def mtime(self):return 0
  with patch.dict(sys.modules,{'truststore':fake_trust}),patch.object(m,'RobotFileParser',Missing),patch.object(m,'urlopen') as download:
   with self.assertRaisesRegex(m.IntakeError,'取得状態を確認できません'):
    m._read_url('https://www.jra.go.jp/keiba/rpdf/pdf/20261107-05tokyo01.pdf')
   download.assert_not_called()
 def test_invalid_url_refused_before_connection(self):
  with self.assertRaises(m.IntakeError):m._read_url('https://example.com/keiba/rpdf/pdf/a.pdf')
if __name__=='__main__':unittest.main(verbosity=2)
