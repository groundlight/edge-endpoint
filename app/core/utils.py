
from fastapi import Request

def get_groundlight_instance(request: Request):
    return request.app.state.groundlight
