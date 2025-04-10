import argparse
import logging as l
from observlib import Observer, OBSERVER


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a","--api-endpoint", action = "store", dest = "endpoint", required = True, help = "api endpoint eg: p2pool mini observer/api")
    parser.add_argument("-w","--wallets", nargs = "+", action = "store", dest = "wallets", required = True, help = "wallets to monitor")
    parser.add_argument("-l","--log", help = "specify log level, DEBUG, INFO, WARNING, ERROR, CRITICAL", dest = "log_level", default = "INFO")
    parser.add_argument("-p","--pyroscope-server", help = "pyroscope server address for profiling", dest = "pyroscope", default = None)
    parser.add_argument("-o","--otlp-server", help = "otlp server for spans", dest = "otlp", default = None)

    args = parser.parse_args()
    l.basicConfig(level = args.log_level)
    OBSERVER = Observer("p2pool_exporter",prometheus_gtw = None, pyroscope_server = args.pyroscope, otlp_server = args.otlp)


if __name__ == "__main__":
    run()
