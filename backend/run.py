import uvicorn


def main() -> None:
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=18765)


if __name__ == "__main__":
    main()
