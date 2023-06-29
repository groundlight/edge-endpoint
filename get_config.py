#!/usr/bin/env python3

import yaml
import os
from jinja2 import Environment, FileSystemLoader


def get_edge_config(filename):
    with open(filename, "r") as ymlfile:
        config = yaml.safe_load(ymlfile)
    return config


def configure_proxy_template_parameters(config):
    """
    Render the template with data and write the output
    """
    env = Environment(loader=FileSystemLoader("."))
    template = env.get_template("nginx.conf.j2")

    output_from_parsed_template = template.render(
        prod_server=config["server-endpoints"]["prod-server"], integ_server=config["server-endpoints"]["integ-server"]
    )

    with open("nginx.conf", "w") as config_file:
        config_file.write(output_from_parsed_template)


def set_motion_detection_env_vars(config):
    with open(".env", "a") as envfile:
        percentage_threshold = str(config["motdet"]["percentage-threshold"])
        val_threshold = str(config["motdet"]["val-threshold"])

        envfile.write(f"MOTDET_PERCENTAGE_THRESHOLD={percentage_threshold}\n")
        envfile.write(f"MOTDET_VAL_THRESHOLD={val_threshold}")


if __name__ == "__main__":
    config = get_edge_config(filename="edge.yaml")
    configure_proxy_template_parameters(config=config)
    set_motion_detection_env_vars(config=config)
