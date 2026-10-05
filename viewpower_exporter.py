#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@file viewpower_exporter.py
@brief Prometheus exporter for ViewPower.

This program queries the ViewPower HTTP API and exposes
UPS data through a Prometheus-compatible HTTP endpoint.

ViewPower API endpoint:

    /ViewPower/workstatus/reqMonitorData

Prometheus endpoint:

    /metrics

"""


import argparse
import json
import logging
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from prometheus_client import (
    CollectorRegistry,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger("viewpower-exporter")


# ---------------------------------------------------------------------------
# UPS data
# ---------------------------------------------------------------------------

@dataclass
class UPSMetrics:
    """
    @brief Values obtained from ViewPower.

    All numeric values are converted to float to make them
    suitable for Prometheus.
    """

    input_voltage: float
    output_voltage: float

    input_frequency: float
    output_frequency: float

    output_current: float
    output_load_percent: float

    battery_capacity: float
    battery_runtime_seconds: float
    battery_voltage: float

    temperature: float

    power_mode: str
    bypass_active: bool


# ---------------------------------------------------------------------------
# ViewPower client
# ---------------------------------------------------------------------------

class ViewPowerClient:
    """
    @brief HTTP client for the ViewPower API.
    """

    def __init__(self, base_url: str, timeout: float = 5.0):
        """
        @param base_url Base URL of the ViewPower installation.
        @param timeout Maximum HTTP request timeout in seconds.
        """

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.invalid_fields = []

    def get_metrics(self) -> UPSMetrics:
        """
        @brief Query ViewPower and return the current UPS data.

        @return UPSMetrics containing the current UPS values.

        @throws RuntimeError if ViewPower returns invalid data.
        """

        endpoint = (
            f"{self.base_url}"
            "/workstatus/reqMonitorData"
        )

        logger.debug(
            "Requesting ViewPower endpoint: %s",
            endpoint,
        )

        request = Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": "viewpower-prometheus-exporter",
            },
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout,
            ) as response:

                body = response.read().decode(
                    "utf-8",
                    errors="replace",
                )

        except HTTPError as exc:
            raise RuntimeError(
                f"ViewPower returned HTTP {exc.code}"
            ) from exc

        except URLError as exc:
            raise RuntimeError(
                f"Unable to connect to ViewPower: {exc.reason}"
            ) from exc

        except TimeoutError as exc:
            raise RuntimeError(
                "Timeout connecting to ViewPower"
            ) from exc

        try:
            data = json.loads(body)

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "ViewPower returned invalid JSON"
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                "Unexpected ViewPower response format"
            )

        work_info = data.get("workInfo")
        
        if not isinstance(work_info, dict):
            raise RuntimeError(
                "ViewPower response does not contain "
                "'workInfo'"
            )

        self.invalid_fields = []

        try:
            input_voltage = self._float(
                work_info,
                "inputVoltage",
            )
        except (KeyError, ValueError, TypeError):
            input_voltage = 0.0
            self.invalid_fields.append("inputVoltage")

        try:
            output_voltage = self._float(
                work_info,
                "outputVoltage",
            )
        except (KeyError, ValueError, TypeError):
            output_voltage = 0.0
            self.invalid_fields.append("outputVoltage")

        try:
            input_frequency = self._float(
                work_info,
                "inputFrequency",
            )
        except (KeyError, ValueError, TypeError):
            input_frequency = 0.0
            self.invalid_fields.append("inputFrequency")

        try:
            output_frequency = self._float(
                work_info,
                "outputFrequency",
            )
        except (KeyError, ValueError, TypeError):
            output_frequency = 0.0
            self.invalid_fields.append("outputFrequency")

        try:
            output_current = self._float(
                work_info,
                "outputCurrent",
            )
        except (KeyError, ValueError, TypeError):
            output_current = 0.0
            self.invalid_fields.append("outputCurrent")

        try:
            output_load_percent = self._float(
                work_info,
                "outputLoadPercent",
            )
        except (KeyError, ValueError, TypeError):
            output_load_percent = 0.0
            self.invalid_fields.append("outputLoadPercent")

        try:
            battery_capacity = self._float(
                work_info,
                "batteryCapacity",
            )
        except (KeyError, ValueError, TypeError):
            battery_capacity = 0.0
            self.invalid_fields.append("batteryCapacity")

        try:
            battery_runtime_minutes = self._float(
                work_info,
                "batteryRemainTime",
            )
        except (KeyError, ValueError, TypeError):
            battery_runtime_minutes = 0.0
            self.invalid_fields.append("batteryRemainTime")

        try:
            battery_voltage = self._float(
                work_info,
                "batteryVoltage",
            )
        except (KeyError, ValueError, TypeError):
            battery_voltage = 0.0
            self.invalid_fields.append("batteryVoltage")

        try:
            temperature = self._float(
                work_info,
                "temperature",
            )
        except (KeyError, ValueError, TypeError):
            temperature = 0.0
            self.invalid_fields.append("temperature")

        if self.invalid_fields:
            logger.debug(
                "Invalid ViewPower fields: %s",
                ", ".join(self.invalid_fields),
            )

        power_mode = str(
            work_info.get("workMode", "unknown")
        )

        bypass_active = bool(
            work_info.get("bypassActive", False)
        )

        return UPSMetrics(
            input_voltage=input_voltage,
            output_voltage=output_voltage,

            input_frequency=input_frequency,
            output_frequency=output_frequency,

            output_current=output_current,
            output_load_percent=output_load_percent,

            battery_capacity=battery_capacity,

            # Convert ViewPower minutes to seconds.
            battery_runtime_seconds=(
                battery_runtime_minutes * 60.0
            ),

            battery_voltage=battery_voltage,

            temperature=temperature,

            power_mode=power_mode,
            bypass_active=bypass_active,
        )

    @staticmethod
    def _float(
        data: dict,
        key: str,
    ) -> float:
        """
        @brief Convert a ViewPower field to float.

        """

        value = data[key]

        if value is None or value == "":
            raise ValueError(
                f"Empty value for '{key}'"
            )

        return float(value)


# ---------------------------------------------------------------------------
# Prometheus exporter
# ---------------------------------------------------------------------------

class ViewPowerExporter:
    """
    @brief Converts ViewPower data into Prometheus metrics.
    """

    def __init__(self, client: ViewPowerClient):
        """
        @param client ViewPower API client.
        """

        self.client = client

    def collect(self) -> bytes:
        """
        @brief Query ViewPower and generate Prometheus metrics.

        @return Prometheus metrics in text format.
        """

        registry = CollectorRegistry()

        # -------------------------------------------------------------------
        # Electrical metrics
        # -------------------------------------------------------------------

        input_voltage = Gauge(
            "viewpower_input_voltage_volts",
            "UPS input voltage in volts",
            registry=registry,
        )

        output_voltage = Gauge(
            "viewpower_output_voltage_volts",
            "UPS output voltage in volts",
            registry=registry,
        )

        input_frequency = Gauge(
            "viewpower_input_frequency_hertz",
            "UPS input frequency in hertz",
            registry=registry,
        )

        output_frequency = Gauge(
            "viewpower_output_frequency_hertz",
            "UPS output frequency in hertz",
            registry=registry,
        )

        output_current = Gauge(
            "viewpower_output_current_amperes",
            "UPS output current in amperes",
            registry=registry,
        )

        output_load = Gauge(
            "viewpower_output_load_percent",
            "UPS output load percentage",
            registry=registry,
        )

        # -------------------------------------------------------------------
        # Apparent power
        # -------------------------------------------------------------------

        output_apparent_power = Gauge(
            "viewpower_output_apparent_power_va",
            "UPS output apparent power in volt-amperes",
            registry=registry,
        )

        # -------------------------------------------------------------------
        # Battery metrics
        # -------------------------------------------------------------------

        battery_capacity = Gauge(
            "viewpower_battery_capacity_percent",
            "UPS remaining battery capacity percentage",
            registry=registry,
        )

        battery_runtime = Gauge(
            "viewpower_battery_runtime_seconds",
            "Estimated UPS remaining runtime in seconds",
            registry=registry,
        )

        battery_voltage = Gauge(
            "viewpower_battery_voltage_volts",
            "UPS battery voltage in volts",
            registry=registry,
        )

        # -------------------------------------------------------------------
        # Temperature
        # -------------------------------------------------------------------

        temperature = Gauge(
            "viewpower_temperature_celsius",
            "UPS temperature in degrees Celsius",
            registry=registry,
        )

        # -------------------------------------------------------------------
        # Status
        # -------------------------------------------------------------------

        exporter_up = Gauge(
            "viewpower_exporter_up",
            "Whether ViewPower metrics were successfully collected",
            registry=registry,
        )

        power_mode = Gauge(
            "viewpower_power_mode_info",
            "Current ViewPower power mode",
            ["mode"],
            registry=registry,
        )

        bypass_active = Gauge(
            "viewpower_bypass_active",
            "Whether UPS bypass mode is active",
            registry=registry,
        )

        try:
            metrics = self.client.get_metrics()

            # ----------------------------------------------------------------
            # Electrical values
            # ----------------------------------------------------------------

            input_voltage.set(
                metrics.input_voltage
            )

            output_voltage.set(
                metrics.output_voltage
            )

            input_frequency.set(
                metrics.input_frequency
            )

            output_frequency.set(
                metrics.output_frequency
            )

            output_current.set(
                metrics.output_current
            )

            output_load.set(
                metrics.output_load_percent
            )

            # ----------------------------------------------------------------
            # Apparent power
            #
            # VA = V × A
            # ----------------------------------------------------------------

            apparent_power = (
                metrics.output_voltage
                * metrics.output_current
            )

            output_apparent_power.set(
                apparent_power
            )

            # ----------------------------------------------------------------
            # Battery values
            # ----------------------------------------------------------------

            battery_capacity.set(
                metrics.battery_capacity
            )

            battery_runtime.set(
                metrics.battery_runtime_seconds
            )

            battery_voltage.set(
                metrics.battery_voltage
            )

            # ----------------------------------------------------------------
            # Temperature
            # ----------------------------------------------------------------

            temperature.set(
                metrics.temperature
            )

            # ----------------------------------------------------------------
            # Status
            # ----------------------------------------------------------------

            power_mode.labels(
                mode=metrics.power_mode
            ).set(1)

            bypass_active.set(
                1 if metrics.bypass_active else 0
            )

            exporter_up.set(1)

            logger.debug(
                "ViewPower metrics collected successfully"
            )

        except Exception:
            logger.exception(
                "Unable to collect ViewPower metrics"
            )

            exporter_up.set(0)

        return generate_latest(registry)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class MetricsHandler(BaseHTTPRequestHandler):
    """
    @brief HTTP request handler for the Prometheus exporter.
    """

    exporter = None

    def do_GET(self):
        """
        @brief Handle HTTP GET requests.

        "/"         -> Informational page.
        "/metrics"  -> Prometheus metrics.
        """

        if self.path == "/":
            invalid_fields = self.exporter.client.invalid_fields
            body = (
                "ViewPower Prometheus Exporter\n"
                "Metrics available at /metrics\n"
                "Made by: Nixacy \n"
                "Github: https://github.com/Nixacy/viewpower-exporter\n"
                "\n"
                f"Invalid fields: {', '.join(invalid_fields) if invalid_fields else 'None'}\n"
                ).encode("utf-8")
            

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8",
            )

            self.send_header(
                "Content-Length",
                str(len(body)),
            )

            self.end_headers()

            self.wfile.write(body)

            return

        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()

            return

        data = self.exporter.collect()

        self.send_response(200)

        self.send_header(
            "Content-Type",
            CONTENT_TYPE_LATEST,
        )

        self.send_header(
            "Content-Length",
            str(len(data)),
        )

        self.end_headers()

        self.wfile.write(data)

    def log_message(self, format, *args):
        """
        @brief Send HTTP logs through the application logger.

        HTTP requests are logged at DEBUG level to avoid filling
        the system journal with every Prometheus scrape.
        """

        logger.debug(
            "%s - %s",
            self.client_address[0],
            format % args,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """
    @brief Main entry point of the exporter.
    """

    parser = argparse.ArgumentParser(
        description="ViewPower Prometheus Exporter"
    )

    parser.add_argument(
        "--url",
        default="http:viewpower:15178/ViewPower",
        help=(
            "ViewPower base URL, e.g. "
            "http://127.0.0.1:15178/ViewPower"
        ),
    )

    parser.add_argument(
        "--listen",
        default="0.0.0.0",
        help=(
            "Address to listen on "
            "(default: 0.0.0.0)"
        ),
    )

    parser.add_argument(
        "--port",
        type=int,
        default=9199,
        help="Exporter HTTP port (default: 9199)",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help=(
            "ViewPower HTTP timeout in seconds "
            "(default: 5)"
        ),
    )

    args = parser.parse_args()

    # -----------------------------------------------------------------------
    # Create ViewPower client
    # -----------------------------------------------------------------------

    client = ViewPowerClient(
        base_url=args.url,
        timeout=args.timeout,
    )

    # -----------------------------------------------------------------------
    # Create exporter
    # -----------------------------------------------------------------------

    exporter = ViewPowerExporter(
        client
    )

    MetricsHandler.exporter = exporter

    # -----------------------------------------------------------------------
    # Create HTTP server
    # -----------------------------------------------------------------------

    server = HTTPServer(
        (args.listen, args.port),
        MetricsHandler,
    )

    logger.info(
        "ViewPower exporter listening on %s:%d",
        args.listen,
        args.port,
    )

    logger.info(
        "ViewPower API: %s",
        args.url,
    )

    logger.info(
        "Prometheus metrics: http://%s:%d/metrics",
        args.listen,
        args.port,
    )

    # -----------------------------------------------------------------------
    # Run server
    # -----------------------------------------------------------------------

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        logger.info(
            "Shutting down"
        )

    finally:
        server.server_close()


if __name__ == "__main__":
    main()
