"""Optional real-DS9 tests: WFS_TEST_XVFB=/path/to/Xvfb python -m unittest ...

Always use a private virtual display. Never open windows on the user's desktop.
"""
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image
from point_star_barghini import BarghiniCamera, vectors
from point_star_fits import write_fits

XVFB = os.environ.get('WFS_TEST_XVFB')


@unittest.skipUnless(XVFB and shutil.which('ds9'), 'Set WFS_TEST_XVFB to run isolated DS9 consumer checks')
class DS9ExportTests(unittest.TestCase):
    def test_mono_and_rgb_load_styled_embedded_regions_and_toggle_visibility(self):
        with tempfile.TemporaryDirectory(prefix='wfs-ds9-test-') as tmp:
            folder = Path(tmp)
            read_fd, write_fd = os.pipe()
            with (folder/'xvfb.log').open('w') as log:
                server = subprocess.Popen([XVFB, '-displayfd', str(write_fd), '-screen', '0',
                                           '1280x1024x24', '-nolisten', 'tcp'],
                                          pass_fds=(write_fd,), stdout=log, stderr=log)
                os.close(write_fd)
                try:
                    self.assertTrue(select.select([read_fd], [], [], 5)[0], 'Virtual display did not start')
                    display = os.read(read_fd, 64).decode().strip()
                    self.assertTrue(display.isdigit(), (folder/'xvfb.log').read_text())
                    env = dict(os.environ, DISPLAY=':'+display)
                    camera = BarghiniCamera.initial((600,800),350.,np.eye(3))
                    science = {'planets': {'status':'planet_epoch_ambiguous',
                        'matches':[{'planet':'Mars','measured_x_px':421.25,'measured_y_px':310.5}],
                        'predicted_planets':[{'planet':'Saturn','predicted_x_px':650.25,'predicted_y_px':430.5}]}}
                    (folder/'labelled_stars.json').write_text(json.dumps({'stars':[
                        {'star_id':'a','display_name':'α Lyrae','x_px':400.25,'y_px':301.75}]}))
                    for rgb in (False,True):
                        with self.subTest(rgb=rgb):
                            pixels=np.zeros((600,800,3) if rgb else (600,800),dtype='uint8')
                            Image.fromarray(pixels).save(folder/'input.png')
                            record=write_fits(folder/'input.png',folder,{'camera':camera.serialise()},science)
                            self.assertEqual(record['status'],'exported')
                            script=folder/'check.tcl'
                            script.write_text('''set out [open {%s} w]
if {[catch {
set f $current(frame)
$f precision 12 12 12 12 12 12 12 12 12
puts $out [$f marker list ds9 image icrs degrees 0]
puts $out "COUNT [$f get marker number]"
$f marker show 0
puts $out "HIDDEN [$f get marker show]"
$f marker show 1
puts $out "SHOWN [$f get marker show]"
$f marker show text 0
puts $out "TEXT_HIDDEN [$f get marker show text]"
$f marker show text 1
puts $out "TEXT_SHOWN [$f get marker show text]"
$f crosshair image 422.25 311.5
puts $out "WORLD [$f get crosshair wcs icrs degrees]"
} err opts]} {puts $out "ERROR $err [dict get $opts -errorinfo]"}
close $out
exit
''' % (folder/'ds9.txt'))
                            run=subprocess.run([sys.executable,'-c',
                                'from point_star_fits import view_fits; import sys; view_fits(sys.argv[1], extra_args=["-prefs","no","-xpa","no","-samp","no","-source",sys.argv[2]])',
                                str(folder/'solution.fits'),str(script)],cwd=Path(__file__).parent,
                                env=env,capture_output=True,text=True,timeout=30)
                            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                            text=(folder/'ds9.txt').read_text()
                            self.assertNotIn('ERROR',text)
                            for expected in ['text={Mars (candidate)}','text={Saturn (predicted)}','α Lyrae',
                                             'COUNT 9','HIDDEN 0','SHOWN 1','TEXT_HIDDEN 0','TEXT_SHOWN 1']:
                                self.assertIn(expected,text)
                            shapes=[line for line in text.splitlines() if line.startswith('polygon(')]
                            self.assertEqual(len(shapes),2)
                            self.assertIn('width=2',shapes[0])
                            self.assertNotIn('width=2',shapes[1])
                            self.assertTrue(all('color=magenta' in s and 'fill=1' not in s for s in shapes))
                            circle=next(line for line in text.splitlines() if line.startswith('circle('))
                            self.assertTrue(circle.startswith('circle(401.25,302.75,'),circle)
                            world=next(line.split()[1:] for line in text.splitlines() if line.startswith('WORLD'))
                            ra,dec=map(float,world)
                            np.testing.assert_allclose(camera.project(vectors([ra],[dec]))[0],
                                                       [421.25,310.5],atol=.05)
                finally:
                    os.close(read_fd)
                    server.terminate()
                    server.wait(timeout=5)


if __name__=='__main__': unittest.main()
