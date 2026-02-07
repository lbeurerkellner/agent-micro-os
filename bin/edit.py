import os
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout.controls import BufferControl

async def edit_with_prompt_toolkit(initial_text=""):
    """Simple multi-line editor using prompt_toolkit."""
    
    os.system('cls' if os.name == 'nt' else 'clear')

    # Create a buffer for editing
    buffer = Buffer(multiline=True)
    buffer.text = initial_text
    
    # Track whether to save
    should_save = {'value': False}
    
    # Create key bindings
    kb = KeyBindings()
    
    @kb.add('c-s')  # Ctrl-S to save and exit
    def save_and_exit(event):
        should_save['value'] = True
        event.app.exit(result=buffer.text)
    
    @kb.add('c-q')  # Ctrl-Q to quit without saving
    def quit_without_saving(event):
        should_save['value'] = False
        event.app.exit(result=None)
    
    # Create layout
    help_text = "Ctrl-S: Save and exit | Ctrl-Q: Quit without saving"
    root_container = HSplit([
        Window(content=FormattedTextControl(text=help_text), height=1),
        Window(content=BufferControl(buffer=buffer)),
    ])
    
    # Create application
    app = Application(
        layout=Layout(root_container),
        key_bindings=kb,
        full_screen=True,
    )
    
    # Run the application
    result = await app.run_async()
    
    return result if should_save['value'] else initial_text

async def run(*args):
    """Edit a file using a simple text editor."""
    from system.context import SystemContext
    from fs.utils import resolve_path

    ctx = SystemContext.current()
    if not ctx:
        print("No context found. Please run this command within a SystemContext.")
        return

    if len(args) == 0:
        print("Usage: edit <file>")
        return

    if len(args) > 1:
        print("edit: only single file editing is supported")
        return

    vault = ctx.fs()
    filepath = args[0]

    _, vault_path = resolve_path(filepath, ctx.cwd)

    initial_content = ""
    if vault.exists(vault_path):
        if vault.is_dir(vault_path):
            print(f"edit: {filepath}: Is a directory")
            return

        try:
            content_bytes = vault.read(vault_path)
            try:
                initial_content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                print(f"edit: {filepath}: Cannot edit binary file")
                return
        except Exception as e:
            print(f"edit: {filepath}: Error reading file: {e}")
            return

    try:
        edited_content = await edit_with_prompt_toolkit(initial_content)
        if edited_content != initial_content:
            vault.write(vault_path, edited_content.encode('utf-8'))
            print(f"Saved {filepath}")
        else:
            print(f"No changes made to {filepath}")
    except Exception as e:
        print(f"edit: {filepath}: Error: {e}")