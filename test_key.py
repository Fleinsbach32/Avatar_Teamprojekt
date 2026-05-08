from google import genai

client = genai.Client(api_key="AIzaSyDn-r6dcevsL-vlNgp1CVPlyEQzB-ul80E")

for model in client.models.list():
    print(model.name)