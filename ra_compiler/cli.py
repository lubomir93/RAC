# ra_compiler/cli.py
"""The command line interface handler. Handles program set up and user input."""

import os
import argparse
import pathlib
import atexit
import pandas as pd
from rich.console import Console
from rich.table import Table
from .mysql import setup_mysql
from .parser import parse_query
from .translator import RATranslator
from .executor import execute, saved_results
from .utils import clean_exit, print_error, print_debug

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.layout.processors import HighlightMatchingBracketProcessor
    from prompt_toolkit.styles import Style
except ImportError:
    PromptSession = None
    FileHistory = None
    HighlightMatchingBracketProcessor = None
    Style = None

RELATION_LIST_LABELS = [
    ("tables", "Tables"),
    ("temporary_tables", "Temporary tables"),
    ("views", "Virtual views"),
    ("materialized_views", "Materialized views"),
    ("rac_virtual_views", "RAC virtual views"),
]

BRACKET_PAIRS = {
    ')': '(',
    '}': '{',
    ']': '[',
}

prompt_session = None
readline = None

if PromptSession is None:
    # import windows equivalent of readline
    try:
        import readline  # Unix / macOS
    except ImportError:
        # Windows fallback
        import pyreadline3 as readline


def main():
    """Main entry point for the RACompiler command line interface."""

    # set up argument parser
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file", nargs="?", default=".env",
                        help="path to the SQL backend configuration file")
    parser.add_argument("-out", action="store_true",
                        help="save output tables as CSVs to the out/ folder")

    # parse the command line arguments
    args = parser.parse_args()
    rac_setup(args)

def rac_setup(args):
    """Set up the database connection and user interface at start up."""

    # set up the sql database connection
    setup_mysql(args.config_file)

    # display the start up messages
    print("\nWelcome to RACompiler!")
    print("Type 'exit' to quit the application.")
    print("Type 'help' for a list of supported functions and syntax.")
    print("Type 'clear' to clear the screen.")

    # set up for the cli history to view previous queries
    history_file = ".rac_cache/ra_history"

    # create the path to the history file if it doesn't exist yet
    os.makedirs(os.path.dirname(history_file), exist_ok=True)
    configure_prompt(history_file)

    if args.out:
        os.makedirs("out", exist_ok=True)

    run(save_to_out=args.out)

def find_matching_bracket(text, closing_index):
    """Return the index of the matching opening bracket for a closing bracket."""

    if closing_index < 0 or closing_index >= len(text):
        return -1

    closing = text[closing_index]
    opening = BRACKET_PAIRS.get(closing)
    if opening is None:
        return -1

    depth = 0
    for idx in range(closing_index, -1, -1):
        char = text[idx]
        if char == closing:
            depth += 1
        elif char == opening:
            depth -= 1
            if depth == 0:
                return idx

    return -1


def configure_prompt(history_file):
    """Set up the interactive query prompt."""

    global prompt_session

    if PromptSession is not None:
        try:
            prompt_session = PromptSession(
                history=FileHistory(history_file),
                input_processors=[
                    HighlightMatchingBracketProcessor(chars="(){}[]"),
                ],
                reserve_space_for_menu=0,
                style=Style.from_dict({
                    "matching-bracket.cursor": "bg:#444444 #ffffff bold",
                    "matching-bracket.other": "bg:#444444 #ffffff bold",
                }),
            )
            return
        except Exception:
            prompt_session = None

    configure_readline_history(history_file)


def configure_readline_history(history_file):
    """Set up basic history support for the plain input fallback."""

    global readline

    if readline is None:
        try:
            import readline as readline_module
        except ImportError:
            import pyreadline3 as readline_module

        readline = readline_module

    if os.path.exists(history_file):
        readline.read_history_file(history_file)
    readline.set_history_length(50)
    atexit.register(write_readline_history, history_file)


def write_readline_history(history_file):
    """Persist fallback prompt history if the history path is still usable."""

    history_dir = os.path.dirname(history_file)
    if history_dir:
        os.makedirs(history_dir, exist_ok=True)

    readline.write_history_file(history_file)


def clear_screen():
    """Clear the terminal screen using the platform shell command."""

    os.system("cls" if os.name == "nt" else "clear")


def prompt_for_query(prompt='> '):
    """Read a query line using the standard input prompt."""

    try:
        if prompt_session is not None:
            return prompt_session.prompt(prompt)
        return input(prompt)
    except EOFError:
        raise


def run(save_to_out=False, query_counter=0):
    """Repeatedly handle user input, parses queries, and displays results."""

    try:
        while True:
            # grab user input
            query = prompt_for_query()

            # check if the command was a built-in CLI request
            if check_if_help_command(query):
                continue

            # if something goes wrong handling the query, skip to the next one
            result = handle_query(query, query_counter)
            if result is None:
                continue

            # if the result is a relation listing, print each non-empty category
            if isinstance(result, dict):
                show_relation_listing(result)
                continue

            # otherwise, cleanly output just the dataframe results
            show_dataframe(None, result.df)

            # if specified, save the result to a csv file in the out/ folder
            if save_to_out and result.save:
                path = pathlib.Path(f"out/{result.name}.csv").absolute()
                result.df.to_csv(path, index=False)

            query_counter += 1

    except KeyboardInterrupt:
        clean_exit()
    except EOFError:
        clean_exit()
    except Exception as e:
        print_error(f"An Error Occurred: {e}", e)
        run(query_counter+1)


def normalize_cli_command(query):
    """Normalize simple shell-style RAC commands."""

    return query.lower().strip(" /\\,.()")


def check_if_help_command(query):
    """Handle any built-in CLI commands. Return true if one was handled."""

    # if the input is an exit command, cleanly exit the application
    exit_commands = ['exit', 'e', 'quit', 'q']
    command = normalize_cli_command(query)
    if command in exit_commands:
        clean_exit()

    # if the input is a clear command, clear the visible screen
    clear_commands = ['clear']
    if command in clear_commands:
        clear_screen()
        return True

    # if the input is a help command, print out the quick reference doc
    help_commands = ['help', 'h', '-h', '-help']
    if command in help_commands:
        file_path = 'docs/quick_reference.txt'
        with open(file_path, 'r', encoding="utf-8") as file:
            content = file.read()
            print(content)
        return True

    return False

def handle_query(query, query_count=0):
    """Parse, translate, and execute a single query input."""

    # print_debug(f"query: {query}")

    parsed_query = parse_query(query)
    if parsed_query is None:
        return None

    # FOR TESTING: print the parsed query : Lark Tree
    # pretty_parsed = parsed_query.pretty()
    # print_debug(f"Parsed Query: {pretty_parsed}")

    # translate the parsed query into an intermediate representation
    translation = None
    try:
        translation = RATranslator(query_count).transform(parsed_query)
        # FOR TESTING:
        # print_debug(f"Translation: {translation}")
    except Exception as e:
        print_error(f"An error occurred during translation: {e}", "TranslationError")
        return None

    # execute the translated query
    result = execute(translation)
    if result is None:
        return None

    # if the result is a relation listing, return the listing
    if isinstance(result, dict):
        return result

    # otherwise, reset the index then save explicitly named virtual views
    result.df = result.df.reset_index(drop=True)
    if result.save:
        saved_results[result.name] = result
    return result

def show_relation_listing(listing):
    """Print relation listings, omitting empty categories."""

    printed = False
    known_categories = {category for category, _ in RELATION_LIST_LABELS}

    for category, label in RELATION_LIST_LABELS:
        names = listing.get(category, [])
        if not names:
            continue

        print(f"{label}:")
        for name in names:
            print(f" - {name}")
        printed = True

    for category, names in listing.items():
        if category in known_categories or not names:
            continue

        print(f"{category.replace('_', ' ').title()}:")
        for name in names:
            print(f" - {name}")
        printed = True

    if not printed:
        print("No relations found.")


def show_dataframe(df_name, df):
    """Nicely print out a pandas DataFrame with an optional corresponding name."""

    # convert the columns to nullable types for consistency
    df = df.convert_dtypes()

    # use the rich Console to display the table
    console = Console()
    table = Table(title=df_name or None)

    for col in df.columns:
        table.add_column(col)
    for _, row in df.iterrows():
        table.add_row(*[
            "NULL" if pd.isna(v) else str(v)
            for v in row
        ])
    console.print(table)
    return df
