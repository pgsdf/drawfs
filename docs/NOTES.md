# Notes

## Build and load

From the repository root:

```sh
# Copy sources into /usr/src and build the module
sh ./build.sh

# Copy, build, and load the module
sh ./build.sh load
```

If your FreeBSD src tree lives somewhere other than `/usr/src`:

```sh
SRCROOT=/path/to/src sh ./build.sh load
```

## Running tests

```sh
cd tests

# Step 11
sudo python3 step11_surface_mmap_test.py

# Step 12
sudo python3 step12_surface_present_test.py
```

## Troubleshooting

- If you change kernel sources, rerun `sh ./build.sh load` to ensure `/usr/src/sys/dev/drawfs` and `/usr/src/sys/modules/drawfs` are updated before rebuilding.
- If you see old behavior, confirm the module was reloaded:

```sh
kldstat | grep drawfs
```
