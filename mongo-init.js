// Runs once, when the mongodb container initialises an empty data directory.
// Names and credentials come from .env through docker-compose.yml.
const dbName = process.env.MONGO_DATABASE;
const db = db.getSiblingDB(dbName);
db.test.insertOne({ ok: true });

db.createRole({
  role: "videoTagAppRole",
  privileges: [
    {
      resource: { db: dbName, collection: "" },
      actions: ["find", "insert", "update", "remove", "listCollections", "listIndexes", "createIndex", "dropIndex"]
    }
  ],
  roles: []
});

db.createUser({
  user: process.env.MONGO_USERNAME,
  pwd: process.env.MONGO_PASSWORD,
  roles: [
    {
      role: "videoTagAppRole",
      db: dbName
    }
  ]
});
