#!/usr/bin/env python3

import yaml
from jinja2 import Environment, FileSystemLoader

with open("proxy_config.yaml", "r") as ymlfile:
    config = yaml.safe_load(ymlfile)

# Load Jinja2 template
env = Environment(loader=FileSystemLoader("."))
template = env.get_template("nginx.conf.j2")


# Render the template with data and write the output
output_from_parsed_template = template.render(
    prod_server=config["server-endpoints"]["prod-server"],
    integ_server=config["server-endpoints"]["integ-server"],
    motdet_percentage_threshold=config["motdet"]["percentage-threshold"],
    motdet_val_threshold=config["motdet"]["val-threshold"],
)

with open("nginx.conf", "w") as config_file:
    config_file.write(output_from_parsed_template)
