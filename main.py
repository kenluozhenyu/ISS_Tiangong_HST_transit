import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.calculator import router as calculator_router
import os

app = FastAPI(title="ISS & Tiangong Transit Finder")

app.include_router(calculator_router, prefix="/api")

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

@app.get("/results")
async def read_results():
    # Will be handled by frontend routing, serving index.html
    return FileResponse("static/index.html")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
