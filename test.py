import time
import os
os.environ['CURL_CA_BUNDLE'] = '/etc/nginx/ssl/nginx_ed25519.crt'


from groundlight import Groundlight
from PIL import Image
import requests 
import urllib3
from ssl import SSLCertVerificationError 

import ssl

ssl._create_default_https_context = ssl._create_unverified_context


# # Disable urllib3 warnings
# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# # Monkey patching urllib3's PoolManager to always skip SSL verification
# original_pool_manager_init = urllib3.PoolManager.__init__

# def patched_pool_manager_init(self, *args, **kwargs):
#     kwargs['cert_reqs'] = 'CERT_NONE'
#     original_pool_manager_init(self, *args, **kwargs)

# urllib3.PoolManager.__init__ = patched_pool_manager_init


DETECTORS = {
    "dog_detector": {
        "detector_id": "det_2UOxalD1gegjk4TnyLbtGggiJ8p",
        "query": "Is there a dog in the image?",
        "confidence_threshold": 0.9,
    },
    "cat_detector": {
        "detector_id": "det_2UOxao4HZyB9gv4ZVtwMOvdqgh9",
        "query": "Is there a cat in the image?",
        "confidence_threshold": 0.9,
    },
}


def main():
    # gl = Groundlight(endpoint="http://10.45.0.71:30101")
    gl = Groundlight(endpoint="https://localhost:443")
    dog_detector = DETECTORS["dog_detector"]["detector_id"]
    cat_detector = DETECTORS["cat_detector"]["detector_id"]

    dog_image = Image.open("test/assets/dog.jpeg")
    cat_image = Image.open("test/assets/cat.jpeg")

    gl.submit_image_query(detector=dog_detector, image=dog_image)
    gl.submit_image_query(detector=cat_detector, image=cat_image)
    
    
    for _ in range(100):
        gl.submit_image_query(detector=dog_detector, image=dog_image)

        gl.submit_image_query(detector=cat_detector, image=cat_image)


if __name__ == "__main__":
    try:
        # response = requests.get(
        #     "https://localhost:443/device-api/v1/detectors/det_2UOxalD1gegjk4TnyLbtGggiJ8p", 
        #     verify=False
        # )
        # print(f"reponse status = {response.status_code}")
        # print(f"response = {response.json()}")  
        main()
        
    except SSLCertVerificationError as e:
        print(f"SSL Certificate Verification Error: {e}")