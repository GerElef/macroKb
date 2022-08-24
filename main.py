import sys
import multiprocessing as mp
# noinspection PyUnresolvedReferences
import evdev as ev
import threading
from time import sleep, time
# noinspection PyUnresolvedReferences
from evdev import InputDevice, categorize, ecodes as e
from abc import ABC
from typing import Callable, Dict, Tuple, List, Any

from bind_skel import MACRO_CLASSES
# noinspection PyUnresolvedReferences
import user_defined_binds  # DO NOT REMOVE


# --------------------------------------------------- IMPORTANT NOTE ---------------------------------------------------
# All three files (main, bind_skel and user_defined_binds) MUST be only superuser editable. Otherwise, a malicious
#  actor can do anything he wants on the system (as this program is meant to run as a systemctl daemon).
#  https://unix.stackexchange.com/questions/455013/how-to-create-a-file-that-only-sudo-can-read
# --------------------------------------------------- IMPORTANT NOTE ---------------------------------------------------

# https://stackoverflow.com/questions/71121522/turn-py-file-to-an-appimage

# cat /proc/bus/input/devices  | highlight sysrq
#  https://old.reddit.com/r/linux/comments/8geyru/diy_linux_macro_board/
# https://python-evdev.readthedocs.io/en/latest/usage.html#accessing-event-codes


class Combination:
    def __init__(self, *args):
        self.keys = sorted(tuple(args))

    def match(self, path: str):
        elements = sorted(path.split("/"))
        if len(self.keys) != len(elements):
            return False

        for ele, key in zip(elements, self.keys):
            if ele != key:
                return False

        return True


class Bind:
    def __init__(self, combination: Combination, action: Callable):
        self.comb = combination
        self.action = action

    def match(self, path):
        return self.comb.match(path)


class Controller(ABC):
    def __init__(self):
        raise RuntimeError("Cannot instantiate abstract class!")

    def execute(self, key):
        pass


# noinspection PyMissingConstructor
class DefaultController(Controller):
    def __init__(self, mode):
        self.down_keys: List[Any] = []
        self.down_keys_time: List[float] = []
        self.hold_keys: List[Any] = []
        self.up_keys: List[Any] = []
        self.up_keys_time: List[float] = []

        self.duration = .06  # (60ms)
        self.mode = mode

    def execute(self, key):
        # remove old keys and add the new one
        self.__transfer_key_states()
        self.__add_to_lists(key)
        print(self.down_keys)
        print(self.hold_keys)
        print(self.up_keys)

        if key.keystate == key.key_down:
            self.__handle_down()
        if key.keystate == key.key_hold:
            self.__handle_hold()
        if key.keystate == key.key_up:
            self.__handle_up()

    def __transfer_key_states(self):
        # if down, but too old, and not UP, make them go to hold
        # append only the names, no time list needed for hold
        self.hold_keys += self.__remove_old(self.down_keys, self.down_keys_time)[0]
        # get the intersection between hold & up and remove the common elements from hold
        ic = set(self.hold_keys).intersection(self.up_keys)
        self.hold_keys[:] = [k for k in self.hold_keys if k not in ic]
        self.__remove_old(self.up_keys, self.up_keys_time)

    def __add_to_lists(self, key):
        if key.keystate == key.key_down:
            if type(key.keycode) is list:
                for code in key.keycode:
                    self.down_keys.append(code)
                    self.down_keys_time.append(time())
            else:
                self.down_keys.append(key.keycode)
                self.down_keys_time.append(time())
        if key.keystate == key.key_up:
            if type(key.keycode) is list:
                for code in key.keycode:
                    self.up_keys.append(code)
                    self.up_keys_time.append(time())
            else:
                self.up_keys.append(key.keycode)
                self.up_keys_time.append(time())

    def __remove_old(self, l, ll):
        tr: List = []  # to remove
        tr_t: List = []  # to remove (name)
        for n, t in zip(l, ll):
            if time() - t > self.duration:
                tr.append(n)
                tr_t.append(t)

        [l.remove(t) for t in tr]
        [ll.remove(n) for n in tr_t]

        return tr, tr_t

    def __handle_down(self):
        do = self.mode.check_bind_down('/'.join(self.down_keys))
        print("DN " + '/'.join(self.down_keys))
        if do:
            do.action()

    def __handle_hold(self):
        do = self.mode.check_bind_hold('/'.join(self.hold_keys))
        print("HLD " + '/'.join(self.hold_keys))
        if do:
            do.action()

    def __handle_up(self):
        do = self.mode.check_bind_up('/'.join(self.up_keys))
        print("UP " + '/'.join(self.up_keys))
        if do:
            do.action()


class Mode:
    def __init__(self, name):
        self.name = name
        self.down_binds = []
        self.hold_binds = []
        self.up_binds = []

        self.hold_cache_bind = None
        # noinspection PyTypeChecker
        self.controller: Controller = None

    def attach_controller(self, controller):
        self.controller = controller
        return self

    def add_bind_down(self, bind: Bind):
        self.down_binds.append(bind)

    def add_bind_up(self, bind: Bind):
        self.up_binds.append(bind)

    def add_bind_hold(self, bind: Bind):
        self.hold_binds.append(bind)

    def check_bind_down(self, path):
        for bind in self.down_binds:
            if bind.match(path):
                return bind

        return None

    def check_bind_hold(self, path):
        if self.hold_cache_bind and self.hold_cache_bind.match(path):
            return self.hold_cache_bind

        for bind in self.hold_binds:
            if bind.match(path):
                self.hold_cache_bind = bind
                return bind

        return None

    def check_bind_up(self, path):
        for bind in self.up_binds:
            if bind.match(path):
                return bind

        return None


class Keyboard:
    def __init__(self, dev1ce, modes: List[Mode], play_the_lights=True):
        self.dev = dev1ce
        self.modes = modes
        self.mode_index = 0
        self.mode = modes[self.mode_index]
        self.switch_mode_key = "KEY_SCROLLLOCK"
        self.dev.grab()

        if play_the_lights:
            threading.Thread(target=play_light_anim, args=(self.dev, .334,)).start()

    def main(self):
        for event in self.dev.read_loop():
            if event.type == e.EV_KEY:
                key = categorize(event)
                # handle switch_mode_key edge-case
                if type(key.keycode) is not list:
                    if key.keycode == self.switch_mode_key:
                        if key.keystate == key.key_down:
                            self.advance_mode()
                        continue

                self.mode.controller.execute(key)

    def advance_mode(self):
        lm = len(self.modes)
        self.mode_index += 1
        if self.mode_index == lm:
            self.mode_index = 0
        self.mode = self.modes[self.mode_index]


def play_light_anim(devve, interval):
    eids = [e.LED_NUML, e.LED_CAPSL, e.LED_SCROLLL]
    state = False
    while True:
        for eid in eids:
            sleep(interval)
            devve.set_led(eid, int(not state))
        state = not state


def create_keyboard_mode(keyboard_name):
    """Create all the applicable keyboard modes for a specific keyboard (name)."""
    kb_modes: Dict[str, List[Mode]] = {}
    for cls in MACRO_CLASSES:
        n = cls.KEYBOARD_NAME
        if n == keyboard_name:
            mode = Mode(n)
            controller = DefaultController(mode)  # default controller
            if cls.CONTROLLER:
                controller = cls.CONTROLLER  # user defined controller
            mode.attach_controller(controller)

            for keys, action in cls.MACROS_DOWN.items():
                mode.add_bind_down(Bind(Combination(*keys), action))

            for keys, action in cls.MACROS_HOLD.items():
                mode.add_bind_hold(Bind(Combination(*keys), action))

            for keys, action in cls.MACROS_UP.items():
                mode.add_bind_up(Bind(Combination(*keys), action))

            if n in kb_modes:
                kb_modes[n].append(mode)
            else:
                kb_modes[n] = [mode]

    return kb_modes


def get_all_keyboard_devices() -> Dict[str, List[str]]:
    devve = {}
    devices = [ev.InputDevice(path) for path in ev.list_devices()]
    for device in devices:
        if "keyboard" in device.name.lower():
            if device.name in devve:
                devve[device.name].append(device.path)
            else:
                devve[device.name] = [device.path]

    return devve


def gg(exctype, value, traceback):
    for p in mp.active_children():
        p.kill()
    print(exctype, value, traceback.format_exc(), file=sys.stderr)
    exit(value)


# TODO remaining:
#  Create flags:
#  flag to dump device capabilities, properly formatted and everything...
#  flag for full blocking mode
#  flag for "non-blocking" mode (it doesn't block input)
#  from get_all_keyboard_devices & print(device.capabilities(verbose=True))
#  toggleable write mode (create virtual UInput) with KEY_SYSRQ (PrtScr) (reserved button)
#   https://python-evdev.readthedocs.io/en/latest/tutorial.html#create-uinput-device-with-capabilities-of-another-device
if __name__ == "__main__":
    sys.excepthook = gg

    keyboards = get_all_keyboard_devices()

    macromodes: Dict[str, List[Mode]] = {}
    for kbn in keyboards.keys():
        kbm = create_keyboard_mode(kbn)
        if kbm:
            macromodes[kbn] = list(kbm.values())[0]

    macroboards = []
    for mmk in macromodes.keys():
        for dev in keyboards[mmk]:
            macroboards.append(Keyboard(InputDevice(dev), macromodes[mmk], play_the_lights=True))

    # https://docs.python.org/3.8/library/multiprocessing.html#the-process-class

    # noinspection PyTypeChecker
    children: List[mp.Process] = []
    for board in macroboards:
        children.append(mp.Process(target=board.main))
        children[-1].start()

    for child in children:
        child.join()

    exit(0)
