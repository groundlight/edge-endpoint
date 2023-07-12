import yaml


def get_edge_config(filename: str) -> dict:
    with open(filename, "r") as ymlfile:
        config = yaml.safe_load(ymlfile)
    return config


if __name__ == "__main__":
    config = get_edge_config(filename="configs/edge.yaml")
