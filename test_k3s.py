from groundlight import Groundlight


def main():
    gl = Groundlight(endpoint="http://10.45.0.71:32503")
    # gl = Groundlight(endpoint="http://10.43.214.51:30222")

    det = "det_2VSCHUvWYX9O5f1jqGzz5Jn3sNE"

    # det = gl.get_detector(id=detector_id)
    image = "/home/ubuntu/edge-endpoint/test/assets/dog.jpeg"

    iq = gl.submit_image_query(image=image, detector=det)

    print("submitting another image query")
    iq2 = gl.submit_image_query(image=image, detector=det)


if __name__ == "__main__":
    main()
