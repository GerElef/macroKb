import os
import pwd
import subprocess as sp
from typing import Type, List

# noinspection PyTypeChecker
MACRO_CLASSES: List[Type] = []


def __demote(user_uid, user_gid):
    def result():
        os.setgid(user_gid)
        os.setuid(user_uid)

    return result


def run_as_user(*args, cwd_redirect: str = None):
    # thank god for this answer
    #  https://stackoverflow.com/questions/1770209/run-child-processes-as-different-user-from-a-long-running-python-process
    # cwd = current working directory, just fyi
    # we can get current logged in user with os.getlogin()
    logged_in_user, current_directory = (f"{os.getlogin()}", f"/home/{os.getlogin()}")
    if cwd_redirect:
        current_directory = cwd_redirect

    pw_record = pwd.getpwnam(logged_in_user)
    logged_in_user = pw_record.pw_name
    user_home_dir = pw_record.pw_dir
    user_uid = pw_record.pw_uid
    user_gid = pw_record.pw_gid
    env = os.environ.copy()
    env['HOME'] = user_home_dir
    env['LOGNAME'] = logged_in_user
    env['PWD'] = current_directory
    env['USER'] = logged_in_user
    sp.Popen(
        args, preexec_fn=__demote(user_uid, user_gid), cwd=current_directory, env=env
    )


def macro_class(cls):
    global MACRO_CLASSES

    KEYBOARD_NAME = "KEYBOARD_NAME"
    MACROS_DOWN = "MACROS_DOWN"
    MACROS_UP = "MACROS_UP"
    MACROS_HOLD = "MACROS_HOLD"

    NAME_EXISTS = False
    MACROS_DOWN_EXISTS = False
    MACROS_UP_EXISTS = False
    MACROS_HOLD_EXISTS = False

    for key in cls.__dict__.keys():
        if key == KEYBOARD_NAME:
            NAME_EXISTS = True

        if key == MACROS_DOWN:
            MACROS_DOWN_EXISTS = True

        if key == MACROS_UP:
            MACROS_UP_EXISTS = True

        if key == MACROS_HOLD:
            MACROS_HOLD_EXISTS = True

    all_ok = NAME_EXISTS and MACROS_UP_EXISTS and MACROS_DOWN_EXISTS and MACROS_HOLD_EXISTS
    if not all_ok:
        raise AttributeError("missing class attribute")

    MACRO_CLASSES.append(cls)

    return cls
