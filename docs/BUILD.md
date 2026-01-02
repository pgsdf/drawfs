# Building drawfs

## Requirements
- FreeBSD 14 or newer
- Full `/usr/src` tree

## Build

```sh
sudo cp -R sys/dev/drawfs /usr/src/sys/dev/
sudo cp -R sys/modules/drawfs /usr/src/sys/modules/

cd /usr/src/sys/modules/drawfs
sudo make clean
sudo make
```

Load:
```sh
OBJDIR=$(sudo make -V .OBJDIR)
sudo kldload "$OBJDIR/drawfs.ko"
```


## Step 11 mmap
See `tests/step11_surface_mmap_test.py`.
