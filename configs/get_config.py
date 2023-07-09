import yaml
from jinja2 import Environment, FileSystemLoader


def get_edge_config(filename: str) -> dict:
    with open(filename, "r") as ymlfile:
        config = yaml.safe_load(ymlfile)
    return config


def configure_proxy_template_parameters(config: dict) -> None:
    """
    Render the template with data and write the output
    """
    env = Environment(loader=FileSystemLoader("."))
    template = env.get_template("configs/nginx.conf.j2")

    output_from_parsed_template = template.render(proxied_edge_server=config["server-endpoints"]["edge-server"])

    with open("nginx.conf", "w") as config_file:
        config_file.write(output_from_parsed_template)
        
def set_motion_detection_env_vars(config: dict) -> None:
    with open(".env", "a") as envfile:
        percentage_threshold = str(config["motdet"]["percentage-threshold"])
        val_threshold = str(config["motdet"]["val-threshold"])

        envfile.write(f"MOTDET_PERCENTAGE_THRESHOLD={percentage_threshold}\nMOTDET_VAL_THRESHOLD={val_threshold}")



if __name__ == "__main__":
    config = get_edge_config(filename="configs/edge.yaml")
    configure_proxy_template_parameters(config=config)
