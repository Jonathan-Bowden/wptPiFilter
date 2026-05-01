# Installing wptPiFilter

## Background
The goal of wptPiFilter is to offload the number of network connected devices from DAQserver or TM onto a secondary Raspberry Pi. There are limitations to how many WPT can be connected to one DAQserver network interface card in this case the Pi would be the edge filtering device so that each Pi would act as the Access Point and the DAQserver PC would only have one network device connected over Ethernet being the Pi running wptPiFilter. When it is running wptPiFilter mediates all messages between DAQserver and the WPTs and bundles all the data messages into one larger buffered message that is sent at the highest scan rate of all the WPTs. It can be installed on a Raspberry Pi 5 device.

## Git Project Cloning
On the Pi make find a location like maybe your Documents folder and open a terminal in the folder. After you have a terminal open in the folder where you want to copy the wptPiProject you can run the git clone command.

```bash
cd ~            # Takes you to hour user root directory
cd Documents    # Assuming you want to put the project in ~/Documents folder
git clone https://github.com/Jonathan-Bowden/wptPiFilter.git
```

## Config File install.cfg
Before running the installation script you need to edit the install.cfg file to reflect your specific PI and Hotspot setup. The main properties you need to know for this step are IP addresses and the specific ssid and psk for the wifi hotspot you want the wireless sensors to connect to on the PI.

## Install Script install.sh
On the PI run install.sh from a terminal within the wptPiFilter root folder.

```bash
cd ~/Documents/wptPiFilter  # Assuming the project is in ~/Documents
sudo bash install.sh
```

## Post-Install Wifi and NetworkFiltering Scripts nft-apply.sh and wifi-enable.sh
After running the install.sh script and not getting any errors or missing dependencies you can run the two follow up scripts. The locations where they are saved and how to run them should be printed into the terminal at the end of successfully running install.sh

```bash
sudo /usr/local/bin/wifi-hotspot.sh
sudo /usr/local/bin/nft-apply.sh
```

# Daq_Server PC Adding Routes

Once you have your wptPiFilter running on your PI you need to add routes to any PCs running daq_server on the same Ethernet network as the PI. You will need to know the wifi subnets of all the hotspots running on the PI and you will need to know the Ethernet IP Address of the PI.

In this example the PIs Ethernet address will be 192.168.1.94
The PI hotspot subnet address will be 10.42.0.0

```cmd
route print
route delete 10.42.0.0
route -p add 10.42.0.0 mask 255.255.255.0 192.168.1.94
```


## Terms and Definitions from install.cfg
The install.cfg always has 10 main properties and 5 properties for each Accesspoint or Hotspot you are installing on the PI. Unless you have conflicting port usage you don't have to Edit the first 4 Properties in the config file. 

PI

```cfg
TPROXY_PORT=19001
MARK=0x1
UDP1=24680
UDP2=24681

VENV_DIR=.venv
ETH_IFACE=eth0
ETH_ADDR=192.168.1.255
ETH_BATCH=192.168.1.92
SERIALNUM=21

AP_COUNT=2

AP_0_WLAN_IFACE=wlan0
AP_0_SSID=VMC-WXCVR
AP_0_WIFI_PSK=vehicle1
AP_0_CONNECTION_NAME=VMC-WXCVR
AP_0_SUBNET=10.24.0.0/24
```