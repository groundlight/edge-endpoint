from groundlight import Groundlight
from PIL import Image

from app.core.utils import safe_call_sdk

img = Image.open("load-testing/images/dog.jpeg")
det_id = "det_2rGydJrU2eBfiACDilkvhgTp1Xz"

gl = Groundlight()
print("finished creating groundlight client")

input("Press Enter to continue...")


try:
    res = safe_call_sdk(gl.submit_image_query, detector=det_id, image=img, wait=0)
    print("finished sdk call")
except Exception as e:
    print("Debug: Exception caught in test:", e)
