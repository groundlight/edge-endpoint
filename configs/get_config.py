import yaml


def get_edge_config(filename: str) -> dict:
    with open(filename, "r") as ymlfile:
        config = yaml.safe_load(ymlfile)
    return config


def set_motion_detection_env_vars(config: dict) -> None:
    with open(".env", "a") as envfile:
        percentage_threshold = str(config["motdet"]["percentage-threshold"])
        val_threshold = str(config["motdet"]["val-threshold"])
        enabled = str(config["motdet"]["enabled"])
        max_time_between_images = str(config["motdet"]["max-time-between-images"])

        envfile.write(
            f"MOTION_DETECTION_PERCENTAGE_THRESHOLD={percentage_threshold}\n"
            f"MOTION_DETECTION_VAL_THRESHOLD={val_threshold}\n"
            f"MOTION_DETECTION_ENABLED={enabled}\n"
            f"MOTION_DETECTION_MAX_TIME_BETWEEN_IMAGES={max_time_between_images}"
        )


# This gets used in the Dockerfile to generate a .env file
# used for motion detection. In the future we might not need
# to use a .env file for motion detection parameters, but until
# then, this file is needed.
if __name__ == "__main__":
    config = get_edge_config(filename="configs/edge.yaml")
    set_motion_detection_env_vars(config=config)