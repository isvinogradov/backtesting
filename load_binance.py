import os
import shutil

import pandas as pd
import requests

from shared.enums import Symbol

YEAR = 2026
TF_RESOLUTION = "5m"
BINANCE_URL_FORMAT = \
    "https://data.binance.vision/data/futures/um/monthly/klines/{t}/{tf}/{t}-{tf}-{yyy}-{mon}.zip"
FILE_FORMAT = "{sym}-{timeframe}-{yyyy}-{num}.{ext}"


def check_file_exists(ticker: Symbol, ix: int) -> bool:
    filename = FILE_FORMAT.format(
        sym=ticker.usdt_pair,
        timeframe=TF_RESOLUTION,
        yyyy=YEAR,
        num=str(ix).zfill(2),
        ext="csv",
    )
    exists = os.path.isfile(filename)
    if exists:
        return True
    else:
        print(f"File not found: {filename}")
        return False


def download_one_file(url: str, filename: str) -> bool:
    r = requests.get(url, stream=True)
    if r.ok:
        print(f"Saving to: {os.path.abspath(filename)}")
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 8):
                if chunk:
                    f.write(chunk)
                    f.flush()
                    os.fsync(f.fileno())
        return True
    else:  # HTTP status code 4XX/5XX
        print(f"Download failed: {r.status_code}\n{r.text}")
        return False


def download_and_unzip_files(ticker: Symbol) -> None:
    for ii in range(1, 13):
        zip_file_name = FILE_FORMAT.format(
            sym=ticker.usdt_pair,
            timeframe=TF_RESOLUTION,
            yyyy=YEAR,
            num=str(ii).zfill(2),
            ext="zip",
        )
        dl_res = download_one_file(
            BINANCE_URL_FORMAT.format(
                t=ticker.usdt_pair,
                tf=TF_RESOLUTION,
                yyy=YEAR,
                mon=str(ii).zfill(2),
            ),
            zip_file_name,
        )
        if dl_res:
            shutil.unpack_archive(zip_file_name)
            os.remove(zip_file_name)
            print(f"Removed: {zip_file_name}")


def merge_files_into_one(ticker: Symbol) -> None:
    filenames = [
        FILE_FORMAT.format(
            sym=ticker.usdt_pair,
            timeframe=TF_RESOLUTION,
            yyyy=YEAR,
            num=str(i).zfill(2),
            ext="csv",
        )
        for i in range(1, 13) if check_file_exists(ticker, i)
    ]
    print(filenames)
    df = pd.concat(
        map(pd.read_csv, filenames),
        ignore_index=True,
    )
    df.open_time *= (1 / 1000)
    df.open_time = df.open_time.astype(int)

    new_filename = f"{ticker.lower()}_data_{YEAR}_{TF_RESOLUTION}.csv"
    df.to_csv(
        new_filename,
        index=False,
        columns=["open_time", "open", "high", "low", "close", "volume"],
    )
    print(f"Saved to: {new_filename}")

    # cleanup
    for f in filenames:
        os.remove(f)
        print(f"Removed: {f}")


if __name__ == '__main__':
    tickers: set[Symbol] = {
        Symbol.BTC,
    }
    for t in tickers:
        print(f" LOADING {t} ".center(80, "*"))
        download_and_unzip_files(t)
        merge_files_into_one(t)
        print(f" {t} - DONE ".center(80, "*"))
        print()
