import requests

response = requests.get("https://127.0.0.1:6443", verify=False)
print(response.text)
