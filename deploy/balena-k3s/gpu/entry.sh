# Remove Nouveau modules
sleep 6
echo 0 > /sys/class/vtconsole/vtcon1/bind
sleep 2
rmmod nouveau
sleep 2

# see https://forums.balena.io/t/blacklist-drivers-in-host-os/163437/25

# Insert Nvidia modules
insmod /nvidia/driver/nvidia.ko
insmod /nvidia/driver/nvidia-modeset.ko
insmod /nvidia/driver/nvidia-uvm.ko

/usr/bin/nvidia-smi
nvidia-modprobe

sleep infinity