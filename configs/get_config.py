import yaml


def get_edge_config(filename: str) -> dict:
    with open(filename, "r") as ymlfile:
        config = yaml.safe_load(ymlfile)
    return config

def set_motion_detection_env_vars(config: dict) -> None:
    with open(".env", "a") as envfile:
        percentage_threshold = str(config["motdet"]["percentage-threshold"])
        val_threshold = str(config["motdet"]["val-threshold"])

        envfile.write(f"MOTDET_PERCENTAGE_THRESHOLD={percentage_threshold}\nMOTDET_VAL_THRESHOLD={val_threshold}")


if __name__ == "__main__":
    config = get_edge_config(filename="configs/edge.yaml")
    set_motion_detection_env_vars(config=config)
