from fastapi import Request


def get_groundlight_sdk_instance(request: Request):
    return request.app.state.groundlight
