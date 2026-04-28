import yaml
from loguru import logger


def _str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    if data and data[0].isdigit():
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="'")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def write_yaml(data: dict, path: str):
    dumper = yaml.Dumper
    dumper.add_representer(str, _str_representer)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            Dumper=dumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            indent=4,
            width=2147483647,
        )

    logger.info("Wrote {}", path)
