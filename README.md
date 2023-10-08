# stream-parse-openttd

Python package to parse the contents of OpenTTD save games (in a streaming way)

> Work in progress. Only a small amount of data is extracted


## Usage

```python
from stream_parse_openttd import stream_parse_openttd

with open('path/to/saved-game.sav', 'rb') as f:
    for chunk_id in stream_parse_openttd(iter(lambda: f.read(65536), b'')):
        print(chunk_id)
```
