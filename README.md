# viewpower-exporter
A simple docker image that reads Viwerexporter's exposed api and transforms the data to a prometheus valid format.

It should be compatible with all UPS models compatible with ViewPower, but I can only test it with mine.

# Docker Hub
https://hub.docker.com/repository/docker/nixacy/viewpower-exporter

# Requirements
Una máquina viertual/servidor dedicado con docker compose instalado y un SAI conectado, ya sea directamente si es una máquina real o mediante passthrough del hypervisor.

A virtual machine or dedicated server with Docker Compose installed and a UPS connected, either directly, if it is a physical machine, or via hypervisor passthrough.

# Configuraciones
By default, the service looks for the ViewPower API on the internal Docker network using the service name and its default port (15178).
These details, as well as the IP addresses on which the service listens for requests and the port on which it is exposed, can be modified using commands defined within the Compose file itself. This involves adding a command block to the service configuration:

El servicio por defecto busca la API de ViewPower en la red interna de docker via nombre del servicio y en el puerto por defecto del mismo (15178), estos datos, asi como las IPs de las que va a escuchar peticiones el servicio y el puerto en el que se expone se pueden modificar via commandos definidios en el propio compose. La estructura consistiria en añadir un bloque de command en la configuración del servicio:
```yml
command:
  - "--url"
  - "https://<IP|hostname of viewpower service>:port/viewpower" #default http://viewpower:15178/ViewPower
  - "--listen"
  - "<IPs>" #default 0.0.0.0 (all)
  - "--port"
  - "PORT" # default 9199 (You need to expose this port for prometheus to scrap the data)
```

# Docker-compose example
```yml
services:
  viewpower:
    image: ggong5/viewpower:latest
    container_name: viewpower
    restart: unless-stopped

    ports:
      - "15178:15178"
      - "8005:8005" #ViewPower web service shutdown port

    volumes:
      - /opt/ViewPower/config:/opt/ViewPower/config
      - /opt/ViewPower/datalog:/opt/ViewPower/datalog
      - /opt/ViewPower/log:/opt/ViewPower/log
      - /dev/bus/usb:/dev/bus/usb
    privileged: true
    networks:
      - viewpower

  viewpower-exporter:
    image: nixacy/viewpower-exporter:latest
    container_name: viewpower-exporter
    restart: unless-stopped

    command:
      - "--url"
      - "http://viewpower:15178/ViewPower"
      - "--listen"
      - "0.0.0.0"
      - "--port"
      - "9199"

    ports:
      - "9199:9199"

    networks:
      - viewpower

networks:
  viewpower:
    driver: bridge

```
# Data exposed

```
viewpower_input_voltage_volts 233.8
viewpower_output_voltage_volts 233.7
viewpower_input_frequency_hertz 50.0
viewpower_output_frequency_hertz 50.0
viewpower_output_current_amperes 2.2
viewpower_output_load_percent 18.0
viewpower_output_apparent_power_va 514.14
viewpower_battery_capacity_percent 100.0
viewpower_battery_runtime_seconds 2160.0
viewpower_battery_voltage_volts 82.0
viewpower_temperature_celsius 26.4
viewpower_exporter_up 1.0
viewpower_power_mode_info{mode="Line mode"} 1.0
viewpower_bypass_active 0.0 
```
