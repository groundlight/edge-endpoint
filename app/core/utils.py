from fastapi import Request


def get_groundlight_instance(request: Request):
    return request.app.state.groundlight


def get_motion_detector_instance(request: Request):
    return request.app.state.motion_detector
