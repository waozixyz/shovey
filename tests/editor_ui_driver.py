"""Inspect semantic controls, with clicks scoped to a private test window."""
import json
import subprocess
import time


class EditorUiDriver:
    def __init__(self, folder, child, window):
        self.folder, self.child, self.window = folder, child, window
        self.serial = 0

    def nodes(self):
        self.serial += 1
        pending = self.folder / 'command.next'
        pending.write_text(f'{self.serial}\ttree\n')
        pending.replace(self.folder / 'command')
        reply = self.folder / 'reply'
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            assert self.child.poll() is None, 'Private editor exited'
            if reply.exists():
                result = json.loads(reply.read_text())
                reply.unlink()
                if result.get('serial') == self.serial:
                    assert result.get('ok'), result
                    return result.get('nodes', [])
            time.sleep(.025)
        raise AssertionError('No semantic tree reply from private editor')

    def press(self, label):
        node = next(node for node in self.nodes()
                    if node.get('kind') == 'button' and node.get('label') == label and node.get('visible'))
        assert not node.get('disabled'), f'{label} is disabled'
        x = int(node['visible_x'] + node['visible_width'] / 2)
        y = int(node['visible_y'] + node['visible_height'] / 2)
        subprocess.run(['xdotool', 'mousemove', '--window', self.window, str(x), str(y), 'mousedown', '1'], check=True)
        time.sleep(.08)
        subprocess.run(['xdotool', 'mouseup', '1'], check=True)
        time.sleep(.15)
