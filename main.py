from fastapi import FastAPI
app = FastAPI()
@app.get("/health")
def saglik_kontrolu():
    return {"durum": "calisiyor", "versiyon": "1.0.0"}

