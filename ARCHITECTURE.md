# ARCHITECTURE

drawfs consists of:
- Kernel device /dev/draw
- Optional user space policy daemon (drawd)
- Client libraries

The kernel implements mechanism only.
User space implements windowing, focus, and policy.
