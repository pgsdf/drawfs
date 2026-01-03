Install/build/load:

sudo cp -R sys/dev/drawfs /usr/src/sys/dev/
sudo cp -R sys/modules/drawfs /usr/src/sys/modules/

cd /usr/src/sys/modules/drawfs
sudo make clean
sudo make

OBJDIR=$(sudo make -V .OBJDIR)
sudo kldunload drawfs 2>/dev/null || true
sudo kldload "$OBJDIR/drawfs.ko"

Run test:

cd /path/to/extracted/step11/tests
sudo python3 step11_surface_mmap_test.py
