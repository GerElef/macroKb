# macroKb
Multi-keyboard macro framework. 

Configure your own keyboard in `user_defined_binds.py`.

Flags:
```
usage: main.py [-h] [-d] [-l] [-p] [-e] [-v]

Daemon for multiple macroinstruction keyboards. Switch modes with KEY_SCROLLLOCK.

options:
  -h, --help           show this help message and exit
  -d, --dump-data      Dumps all relevant device (denoted by 'keyboard' keyword) data capabilities to STDOUT.
  -l, --no-lights      Toggles light animation off.
  -p, --print-keys     Prints all keypresses to STDERR for debugging. SECURITY RISK! This switch could leak your passwords if it's running as a daemon.
  -e, --non-exclusive  Enables input toggle with KEY_SYSRQ.
  -v, --version        Current program version.
```

## DISCLAIMER:
THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
