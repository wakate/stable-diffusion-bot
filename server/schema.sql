PRAGMA foreign_keys = ON;
DROP TABLE IF EXISTS queries;
DROP TABLE IF EXISTS responses;

CREATE TABLE queries(
    id INTEGER PRIMARY KEY,
    user TEXT NOT NULL,
    channel TEXT NOT NULL,
    guild TEXT NOT NULL,
    query TEXT NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE TABLE responses(
    id INTEGER PRIMARY KEY,
    query_id INTEGER NOT NULL,
    responded_at DATETIME,
    response BLOB,
    is_nsfw INTEGER NOT NULL,
    FOREIGN KEY(query_id) REFERENCES queries(id)
);