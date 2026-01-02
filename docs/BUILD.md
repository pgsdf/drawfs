# Build and install

## Prerequisites

- FreeBSD 15 with kernel sources in `/usr/src`
- Base build toolchain (clang, make)
- Python 3 for the test harness
- Zig 0.15.2 is optional and only needed if you are building SemaDraw related tooling

## Using build.sh

From the repository root:

```sh
# Copy kernel sources into /usr/src (sys/dev + sys/modules)
./build.sh install

# Build the kmod (uses /usr/src/sys/modules/drawfs)
./build.sh build

# Load the module (also unloads any prior drawfs)
./build.sh load

# Run the test suite (step based harness)
./build.sh test
```

## Manual build

```sh
sudo rsync -a sys/dev/drawfs/ /usr/src/sys/dev/drawfs/
sudo rsync -a sys/modules/drawfs/ /usr/src/sys/modules/drawfs/

cd /usr/src/sys/modules/drawfs
sudo make clean
sudo make

OBJDIR=$(sudo make -V .OBJDIR)
sudo kldunload drawfs 2>/dev/null || true
sudo kldload "$OBJDIR/drawfs.ko"
```

## Running a specific step

```sh
cd tests
sudo python3 step11_surface_mmap_test.py
sudo python3 step12_surface_present_test.py
```
