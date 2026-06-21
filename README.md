# RAC - *Relational Algebra Interpreter*

### Overview

RAC is a tool to parse and execute relational algebra queries by translating them into SQL and running against a MySQL database by default. PostgreSQL is also supported through the database config file.


### Requirements

- Python 3.8 or higher
- MySQL or PostgreSQL database accessible with proper credentials



## Setup Instructions

### 1. Clone the repository

```shell
git clone https://github.com/sydlyn/RelationalAlgebraCompiler.git
cd RelationalAlgebraCompiler
```


### 2. Create and activate a virtual environment

On macOS/Linux: 
```shell
python -m venv venv
source ./venv/bin/activate
```
> Note: you may have to use `python3` or `python3.XX` depending on the version of python that you have installed

On Windows: 
```shell
venv\Scripts\activate
```

### 3. Install dependencies and the package

```shell
pip install flit
flit install --symlink
```
> Note: you may have to use `pip3` or `pip3.XX` depending on the version of pip that you have installed


This will install RAC in editable mode and register the `rac` command.

### 4. Configure your database connection

Create a config file in the project root with your database credentials:

```shell
DB=MySQL                 # optional, defaults to MySQL; use DB=PostgreSQL for PostgreSQL
DB_HOST=your_host  
DB_PORT=your_port        # optional, defaults to 3306 for MySQL or 5432 for PostgreSQL
DB_USER=your_user  
DB_PASSWORD=your_password  
DB_NAME=your_database  
```

> By default, RAC looks for a config file named `.env` in the project root: `RelationalAlgebraCompiler/.env`  
> A different file name can be used, but the file must be specified at run time. 

An `example.env` is provided for user reference and can be copied+edited to create the needed config file:
```
cp example.env .env
```

---

### Usage

Run the RAC command line interface:

```shell
rac [config-file] [-out] [-h]
```
Positional Arguments:
- `config-file`: If no config-file is provided, RAC will look for `.env` file in the project root: `RelationalAlgebraCompiler/.env`  

Options:
- `-out`: Creates a CSV file of a saved result to the `out/` folder
    - *saved results* are considered tables/query results that are renamed with the /rho operation
- `-h`, `--help`: Show program usage options.

## Running Tests

Make sure your database is running and accessible and that program functionality is intact.

Run all tests with:
```shell
python -m unittest discover -s tests -p "test*.py"
```

Or if you use pytest:
```shell
pytest -q 
```

---

### Project Structure
```
RAC/  
├── ra_compiler/        # Main package source code  
│   ├── __main__.py
│   ├── __init__.py  
│   ├── cli.py          # Command line interface entry point  
│   ├── mysql.py        # SQL database connection code
│   ├── parser.py       # Query parsing logic  
│   ├── translator.py   # Query translation to an intermediate representation  
│   ├── executor.py     # Query execution  
│   ├── utils.py        # Program wide helper functions  
│   ├── exceptions.py   # Custom program exceptions  
│   └── grammar.lark    # Query grammar definition  
├── tests/              # Test suite  
│   └── ...             
├── .env                # Created by User database credentials (gitignored)
├── example.env         # Example Config File for database credentials
├── pyproject.toml      # Build configuration using flit  
├── README.md           # This file  
├── docs/               # User guides for query syntax and usage
└── ...
```

---

### Final Notes

- Make sure your database server is up and the `.env` file is correctly set before running.
- `flit install --symlink` ensures that code changes are immediately available without reinstalling.
