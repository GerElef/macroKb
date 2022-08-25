#!/usr/bin/python3

import argparse
import sys
import multiprocessing as mp
# noinspection PyUnresolvedReferences
from collections.abc import Iterable

# noinspection PyUnresolvedReferences
import evdev as ev
import threading
from time import sleep, time
# noinspection PyUnresolvedReferences
from evdev import InputDevice, UInput, categorize, ecodes as e
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

    def get_input_event_type(self) -> Tuple:
        pass

    def execute(self, key, device):
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

    def get_input_event_type(self) -> Tuple:
        return e.EV_KEY,

    def execute(self, key, _):  # we will not be using the device, only passively reacting to events
        # remove old keys and add the new one
        self.__transfer_key_states()
        self.__add_to_list(self.down_keys, self.down_keys_time, key, key.key_down)
        self.__add_to_list(self.up_keys, self.up_keys_time, key, key.key_up)

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

    # noinspection PyMethodMayBeStatic
    def __add_to_list(self, key_list, time_list, key, key_trigger_state):
        if key.keystate == key_trigger_state:
            if type(key.keycode) is list:
                for code in key.keycode:
                    key_list.append(code)
                    time_list.append(time())
            else:
                key_list.append(key.keycode)
                time_list.append(time())

    def __remove_old(self, time_list, name_list):
        tr: List = []  # to remove
        tn_t: List = []  # to remove (name)
        for n, t in zip(time_list, name_list):
            if time() - t > self.duration:
                tr.append(n)
                tn_t.append(t)

        [time_list.remove(t) for t in tr]
        [name_list.remove(n) for n in tn_t]

        # return removed
        return tr, tn_t

    def __handle_down(self):
        do = self.mode.check_bind_down('/'.join(self.down_keys))
        if do:
            do.action()

    def __handle_hold(self):
        do = self.mode.check_bind_hold('/'.join(self.hold_keys))
        if do:
            do.action()

    def __handle_up(self):
        do = self.mode.check_bind_up('/'.join(self.up_keys))
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
    INPUT_MODE_KEY = "KEY_SYSRQ"
    SWITCH_MODE_KEY = "KEY_SCROLLLOCK"

    def __init__(self, dev1ce_path, modes: List[Mode], play_the_lights=True, print_keys=False, exclusive=False):
        self.dev = InputDevice(dev1ce_path)
        self.dev_path = dev1ce_path

        self.modes = modes
        self.mode_index = 0
        self.mode = modes[self.mode_index]

        self.print_keys = print_keys  # cmd switch
        self.exclusive = exclusive  # cmd switch
        self.write_mode = False
        self.virtual_keyboard: InputDevice = None

        self.dev.grab()
        if play_the_lights:
            threading.Thread(target=play_light_anim, args=(self.dev, .334,)).start()

    def main(self):
        for event in self.dev.read_loop():
            if event.type in self.mode.controller.get_input_event_type():
                key = categorize(event)

                if self.print_keys:
                    print(key, file=sys.stderr)

                # if we advanced mode, skip this turn
                if self.advance_mode(key):
                    continue

                # if we toggled inputs, skip this turn
                if self.toggle_inputs(key):
                    continue

                # if we're writing, do not execute any macros/binds
                if self.write_mode:
                    try:
                        self.virtual_keyboard.write_event(event)
                        self.virtual_keyboard.syn()
                    except Exception as e:
                        self.virtual_keyboard.close()
                        self.write_mode = False
                        print(f"Got unexpected exception on {self.virtual_keyboard}\n{e}")
                    continue

                self.mode.controller.execute(key, self.dev)

    def toggle_inputs(self, key):
        if not self.exclusive and type(key.keycode) is not list:
            if key.keycode == Keyboard.INPUT_MODE_KEY:
                if key.keystate == key.key_down:
                    self.write_mode = not self.write_mode
                    if self.write_mode:
                        self.virtual_keyboard = UInput.from_device(self.dev.path, name=f"V_{self.dev.name}")
                    else:
                        self.virtual_keyboard.close()
                    return True
        return False

    def advance_mode(self, key):
        if type(key.keycode) is not list:
            if key.keycode == Keyboard.SWITCH_MODE_KEY:
                if key.keystate == key.key_down:
                    lm = len(self.modes)
                    self.mode_index += 1
                    if self.mode_index == lm:
                        self.mode_index = 0
                    self.mode = self.modes[self.mode_index]
                    return True
        return False


def play_light_anim(devve, interval):
    eids = [e.LED_NUML, e.LED_CAPSL, e.LED_SCROLLL]
    state = False
    while True:
        for eid in eids:
            sleep(interval)
            devve.set_led(eid, int(not state))
        state = not state


# noinspection PyUnresolvedReferences
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
        if "keyboard" in device.name.lower():  # exact match
            if device.name in devve:
                devve[device.name].append(device.path)
            else:
                devve[device.name] = [device.path]

    return devve


def gg(exctype, value, traceback):
    for p in mp.active_children():
        p.kill()
    print(exctype, value, traceback, file=sys.stderr)
    exit(value)


def dump_data():
    devices = [ev.InputDevice(path) for path in ev.list_devices()]
    for device in devices:
        if "keyboard" in device.name.lower():
            capabilities_dict = device.capabilities(verbose=True)
            print(f"Device {device.name}\nPath:{device.path}")
            for cdkey in capabilities_dict.keys():
                if type(capabilities_dict[cdkey]) in (list, dict, set):
                    print(f"\t{cdkey}")
                    for v in capabilities_dict[cdkey]:
                        print(f"\t\t{v}")
                else:
                    print(f"{cdkey} {capabilities_dict[cdkey]}")


def parse_args():
    global print_keys_switch, light_switch, exclusivity
    PROGRAM_VERSION = "1.2.0"

    # https://stackoverflow.com/questions/7427101/simple-argparse-example-wanted-1-argument-3-results
    parser = argparse.ArgumentParser(description="Daemon for multiple macroinstruction keyboards.\n"
                                                 f"Switch modes with {Keyboard.SWITCH_MODE_KEY}.")
    parser.add_argument("-d", "--dump-data", help="Dumps all relevant device (denoted by 'keyboard' keyword)"
                                                  " data capabilities to STDOUT.", required=False, action="store_true")
    parser.add_argument("-l", "--no-lights", help="Toggles light animation off.", required=False, action="store_true")
    parser.add_argument("-p", "--print-keys", help="Prints all keypresses to STDERR for debugging.\n"
                                                   "SECURITY RISK! This switch could leak your passwords if "
                                                   "it's running as a daemon.", required=False, action="store_true")
    parser.add_argument("-e", "--non-exclusive", help=f"Enables input toggle with {Keyboard.INPUT_MODE_KEY}.",
                        required=False, action="store_true")
    parser.add_argument("-v", "--version", help="Current program version.", required=False, action="store_true")
    args = parser.parse_args().__dict__
    if args["version"]:
        print(f"macroKb {PROGRAM_VERSION}")
        exit(0)

    if args["dump_data"]:
        dump_data()
        exit(0)

    if args["no_lights"]:
        light_switch = False

    if args["non_exclusive"]:
        light_switch = False
        exclusivity = False

    if args["print_keys"]:
        print_keys_switch = True


# TODO remaining:
#  Create flag for simulating mice as well (???)/ or some way to add a bind that SIMULATES a mouse axis movement
if __name__ == "__main__":
    # with UInput.from_device("/dev/input/event11", name="okayke-TEST") as vk:
    #     vk.write(e.EV_KEY, e.KEY_H, 1)
    #     vk.write(e.EV_KEY, e.KEY_H, 0)
    #     vk.syn()
    light_switch = True
    exclusivity = True
    print_keys_switch = False

    parse_args()

    sys.excepthook = gg

    keyboards = get_all_keyboard_devices()
    macromodes: Dict[str, List[Mode]] = {}
    for kbn in keyboards.keys():
        kbm = create_keyboard_mode(kbn)
        if kbm:
            macromodes[kbn] = list(kbm.values())[0]

    macroboards = []
    for mmk in macromodes.keys():
        for dev_path in keyboards[mmk]:
            macroboards.append(Keyboard(dev_path, macromodes[mmk],
                                        play_the_lights=light_switch,
                                        print_keys=print_keys_switch,
                                        exclusive=exclusivity))

    # https://docs.python.org/3.8/library/multiprocessing.html#the-process-class

    # noinspection PyTypeChecker
    children: List[mp.Process] = []
    for board in macroboards:
        children.append(mp.Process(target=board.main))
        children[-1].start()

    for child in children:
        child.join()

    exit(0)
