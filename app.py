import tkinter as tk
import time
import threading
import os
from PIL import ImageGrab
from google import genai
from google.genai import types
import json
import keyboard
import dotenv
from PIL import Image

# UI CONFIGURATION
class UIConfig:
    COUNTDOWN = 12
    BG_COLOR = "#000000"
    TEXT_COLOR = "#FFFFFF"
    WINDOW_WIDTH = 108
    WINDOW_HEIGHT = 32
    FRAME1_WIDTH = 32
    FRAME2_WIDTH = 76

# CONFIGURATION AND SETUP
def load_environment():
    """Load multiple API keys from environment"""
    dotenv.load_dotenv()
    # Get the string and split it into a list
    keys_str = os.getenv("API_KEYS", "")
    api_keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    
    if not api_keys:
        # Fallback to the single API_KEY if only One API_KEY is provided
        single_key = os.getenv("API_KEY")
        if single_key:
            api_keys = [single_key]
        else:
            print("No API keys found in .env")
            exit(1)
    
    return api_keys

def load_context_text():
    """Load helper text from context.txt file"""
    try:
        with open("context.txt", "r") as f:
            text_help = f.read().strip()
            if text_help == "Put anything related to the QCMs here, like course text or QCMS with answers":
                return ""
            elif len(text_help) > 5:
                return f"These are some examples of questions you might encounter with their answers they are absolutely right:\n{text_help}\n\n"
            else:
                return ""
    except FileNotFoundError:
        return ""

def create_prompt(text_help=""):
    """Create the AI prompt with context"""
    return f"""
Analyze the image and answer the multiple choice question (QCM/MCQ) shown.

Instructions:
1. Carefully read the question and all answer options
2. Determine if this is a single-answer or multiple-answer question.
3. Select the most appropriate answer(s)
4. Provide your response in valid JSON format with these exact key:
   - "final_choice": The letter(s) only (e.g., "A" for single answer, "A,C,E" for multiple answers)

Format requirements:
- For single answers: Use one letter (e.g., "A", "B", "C", etc.)
- For multiple answers: Use comma-separated letters with no spaces (e.g., "A,C", "A,B", "B,C,D" etc.)
- If no question is visible in the image, return "X"

IMPORTANT:
- Do not include any additional text or explanations in the response
- Ensure the response is strictly in JSON format

JSON response format:
{{
    "final_choice": the_answer_here
}}

# If you cannot determine the answer, return "X" as the final choice.

{text_help}

The image is provided below. Analyze it and provide your answer in the specified JSON format.
"""

# AI PROCESSING
class AIProcessor:
    def __init__(self, api_keys):
        self.api_keys = api_keys
        self.current_key_index = 0
        self.model_id = 'gemini-3-flash-preview' 
        self.prompt = create_prompt(load_context_text())
        self._setup_current_client()
        '''
        For the next developper : 
        If you're having issues setting  up your model, uncomment the code below to see available models
        '''
        # for model in self.client.models.list():
        #     print(f"Available: {model.name}")

    def _setup_current_client(self):
        """Initializes the client with the current key index"""
        key = self.api_keys[self.current_key_index]
        self.client = genai.Client(api_key=key)
        print(f"Using API Key #{self.current_key_index + 1}")

    def rotate_key(self):
        """Switch to the next available key"""
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self._setup_current_client()

    def validate_api_key(self):
        try:
            response = self.client.models.generate_content(
                model=self.model_id, contents="Hi"
            )
            return True, "OK"
        except Exception as e:
            print(f"DEBUG: Actual API Error: {e}")
            return False, str(e)
            
            
    def process_screenshot(self, temp_filename):
        """Send screenshot with retry logic for rate limits"""
        img = Image.open(temp_filename)
        
        # Try up to the number of keys we have
        for _ in range(len(self.api_keys)):
            try:
                response = self.client.models.generate_content(
                    model=self.model_id,
                    contents=[self.prompt, img]
                )
                
                # Parse JSON (Keeping your original logic)
                text_response = response.text
                json_start = text_response.find('{')
                json_end = text_response.rfind('}') + 1
                
                if json_start >= 0 and json_end > json_start:
                    return json.loads(text_response[json_start:json_end])
                return {"final_choice": "X"}

            except Exception as e:
                error_msg = str(e).lower()
                # Check specifically for Rate Limit (429)
                if "429" in error_msg or "quota" in error_msg:
                    print(f"Key {self.current_key_index + 1} hit limit. Rotating...")
                    self.rotate_key()
                    time.sleep(1) # Short pause before retry
                    continue 
                else:
                    # If it's a different error, don't rotate, just return it
                    return {"error": str(e), "final_choice": "X"}
        
        return {"error": "All keys exhausted rate limits", "final_choice": "X"}

# SCREENSHOT HANDLER
class ScreenshotHandler:
    def __init__(self, ai_processor, update_callback):
        self.ai_processor = ai_processor
        self.update_callback = update_callback
        
    def capture_and_process(self):
        """Capture screenshot and process with AI"""
        delete_temp_files = True
        self.update_callback("WAIT...")
        
        try:
            screenshot = ImageGrab.grab()
            temp_filename = f"screenshots/temp_screenshot{int(time.time())}.png"
            screenshot.save(temp_filename)
            
            response = self.ai_processor.process_screenshot(temp_filename)
            choice = response.get("final_choice", "X").upper().strip()
            
            if choice != "X":
                delete_temp_files = False
            
            return choice
            
        except Exception:
            return "X"
        finally:
            if os.path.exists(temp_filename) and delete_temp_files:
                os.remove(temp_filename)

# MAIN APPLICATION
class ScreenshotApp:
    def __init__(self, root):
        self.root = root
        self.config = UIConfig()
        self.api_keys = load_environment()
        self.ai_processor = AIProcessor(self.api_keys)
        self.screenshot_handler = ScreenshotHandler(self.ai_processor, self._update_result)
        
        # App state
        self.running = True
        self.visible = True
        self.paused = False
        self.countdown = self.config.COUNTDOWN
        self.screenshot_thread = None
        
        self._setup_window()
        self._init_ui()
        self._setup_hotkeys()
        
        # Start operations
        # self.start_screenshot_thread()
        self.update_ui_periodic()
    
    def _setup_window(self):
        """Configure the main window"""
        self.root.title("Screenshot Monitor")
        self.root.geometry(f"{self.config.WINDOW_WIDTH}x{self.config.WINDOW_HEIGHT}")
        self.root.resizable(False, False)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 1)
        self.root.overrideredirect(True)
        self.root.wm_attributes('-transparentcolor', self.config.BG_COLOR)
        
        # Position window
        screen_height = self.root.winfo_screenheight()
        x_position = 16
        y_position = screen_height - 42
        self.root.geometry(f"{self.config.WINDOW_WIDTH}x{self.config.WINDOW_HEIGHT}+{x_position}+{y_position}")
    
    def _init_ui(self):
        """Initialize UI components"""
        # Create frames
        self.frame1 = tk.Frame(self.root, width=self.config.FRAME1_WIDTH, height=self.config.WINDOW_HEIGHT, bg=self.config.BG_COLOR)
        self.frame1.grid(row=0, column=0)
        self.frame1.grid_propagate(False)
        
        self.frame2 = tk.Frame(self.root, width=self.config.FRAME2_WIDTH, height=self.config.WINDOW_HEIGHT, bg=self.config.BG_COLOR)
        self.frame2.grid(row=0, column=1)
        self.frame2.grid_propagate(False)
        
        # Timer display
        self.timer_text = tk.StringVar()
        self.timer_text.set(str(self.config.COUNTDOWN))
        self.timer_label = tk.Label(self.frame1, textvariable=self.timer_text,
                                  bg=self.config.BG_COLOR, fg=self.config.TEXT_COLOR, font=("Arial", 12, "bold"))
        self.timer_label.place(x=5, y=8)
        
        # Result display
        self.result_text = tk.StringVar()
        self.result_text.set("")
        self.result_label = tk.Label(self.frame2, textvariable=self.result_text,
                                   bg=self.config.BG_COLOR, fg=self.config.TEXT_COLOR, font=("Arial", 12, "bold"))
        self.result_label.place(x=8, y=8)
        
        # Setup drag functionality
        self._setup_drag_functionality()
    
    def _setup_drag_functionality(self):
        """Setup window dragging for all widgets"""
        widgets_to_bind = [self.root, self.frame1, self.frame2, self.timer_label, self.result_label]
        for widget in widgets_to_bind:
            widget.bind("<Button-1>", self.start_move)
            widget.bind("<ButtonRelease-1>", self.stop_move)
            widget.bind("<B1-Motion>", self.do_move)
    
    def _setup_hotkeys(self):
        """Setup keyboard shortcuts"""
        keyboard.add_hotkey('shift+a', self.toggle_visibility)
        keyboard.add_hotkey('ctrl+shift', self.take_immediate_screenshot)
        keyboard.add_hotkey('ctrl+space', self.toggle_pause)
        keyboard.add_hotkey('shift+R', self.reload_app)
        keyboard.add_hotkey('shift+ctrl+x', self.on_closing)
    
    def _update_result(self, result):
        """Callback for updating result from screenshot handler"""
        self.root.after(0, self.update_result, result)
    

    # SCREENSHOT OPERATIONS

    def start_screenshot_thread(self):
        """Start the screenshot monitoring thread"""
        if self.screenshot_thread and self.screenshot_thread.is_alive():
            return
        
        self.screenshot_thread = threading.Thread(target=self.screenshot_loop)
        self.screenshot_thread.daemon = True
        self.screenshot_thread.start()
        
    def screenshot_loop(self):
        """Main loop for taking screenshots"""
        while self.running:
            if self.paused or not self.visible:
                time.sleep(1)
                continue
                
            self.countdown = self.config.COUNTDOWN
            
            if not self.running:
                break
                
            choice = self.screenshot_handler.capture_and_process()
            if self.running and self.visible:
                self.root.after(0, self.update_result, choice)
                
            self.countdown_loop()
            
    def countdown_loop(self):
        """Handle countdown between screenshots"""
        while self.countdown > 0 and self.running:
            time.sleep(1)
            if self.running:
                self.root.after(0, lambda: self.root.attributes('-topmost', True))
            if not self.paused and self.visible:
                self.countdown -= 1
    
    def take_immediate_screenshot(self):
        """Take an immediate screenshot and reset timer"""
        self.countdown = 0
    

    # UI UPDATES AND INTERACTIONS

    def update_ui_periodic(self):
        """Update UI elements periodically"""
        if not self.running:
            return
        
        # Update timer display
        current_time = f"{self.countdown:02d}" if self.visible else ""
        self.timer_text.set(current_time)
        
        self.root.after(500, self.update_ui_periodic)

    def update_result(self, result: str):
        """Update the result display"""
        self.result_text.set(result)
        self.root.update_idletasks()
    
    def toggle_visibility(self):
        """Toggle app visibility"""
        self.visible = not self.visible
        if not self.visible:
            self.update_result("")
            self.timer_text.set("")
        else:
            self.update_result("X")
    
    def toggle_pause(self):
        """Toggle pause state"""
        self.paused = not self.paused
        self.update_result("Paused" if self.paused else "Running")
    

    # WINDOW DRAGGING

    def start_move(self, event):
        """Start window drag operation"""
        self.x = event.x
        self.y = event.y

    def stop_move(self, event):
        """Stop window drag operation"""
        self.x = None
        self.y = None

    def do_move(self, event):
        """Move window during drag operation"""
        dx = event.x - self.x
        dy = event.y - self.y
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")
    

    # APP LIFECYCLE

    def validate_gemini_api_key(self):
        """Validate API key and show result"""
        is_valid, message = self.ai_processor.validate_api_key()
        if not is_valid:
            self.show_error("Key Error", message)
        else:
            self.update_result("OK")
    
    def show_error(self, err: str, message: str):
        """Display error and exit"""
        print("error:", err)
        print(message)
        time.sleep(1)
        exit(1)
    
    def reload_app(self):
        """Reload the entire application"""
        try:
            # Stop current operations
            old_running = self.running
            self.running = False
            
            # Wait for thread to finish
            if self.screenshot_thread and self.screenshot_thread.is_alive():
                self.screenshot_thread.join(timeout=3)
                if self.screenshot_thread.is_alive():
                    print("Warning: Old thread didn't stop cleanly")
            
            # Store current position
            current_x = self.root.winfo_x()
            current_y = self.root.winfo_y()
            
            # Clean up
            keyboard.unhook_all()
            for widget in self.root.winfo_children():
                widget.destroy()
            
            # Reconfigure window
            self._setup_window()
            self.root.geometry(f"{self.config.WINDOW_WIDTH}x{self.config.WINDOW_HEIGHT}+{current_x}+{current_y}")
            
            # Reinitialize
            self.running = True
            self.ai_processor = AIProcessor(self.api_key)  # Reload context
            self.screenshot_handler = ScreenshotHandler(self.ai_processor, self._update_result)
            self._init_ui()
            self._setup_hotkeys()
            
            # Restart operations
            self.start_screenshot_thread()
            self.update_ui_periodic()
            
            print("App reloaded successfully")
            
        except Exception as e:
            print(f"Error during app reload: {str(e)}")
            self.running = old_running
    
    def on_closing(self):
        """Handle application closing"""
        self.running = False
        if self.screenshot_thread and self.screenshot_thread.is_alive():
            self.screenshot_thread.join(timeout=2)
        keyboard.unhook_all()
        self.root.destroy()


# MAIN EXECUTION
def create_popup_menu(root, app):
    """Create right-click popup menu"""
    def show_popup(event):
        popup_menu = tk.Menu(root, tearoff=0)
        popup_menu.add_command(label="Close", command=app.on_closing)
        popup_menu.add_command(label="Reload", command=app.reload_app)
        popup_menu.add_command(label="Pause/Resume", command=app.toggle_pause)
        popup_menu.add_command(label="Toggle Visibility", command=app.toggle_visibility)
        popup_menu.add_command(label="Take Screenshot Now", command=app.take_immediate_screenshot)
        popup_menu.tk_popup(event.x_root, event.y_root)
    
    return show_popup

def main():
    """Main application entry point"""
    # Create screenshots directory
    if not os.path.exists("screenshots"):
        os.makedirs("screenshots")
    
    # Initialize and run app
    root = tk.Tk()
    app = ScreenshotApp(root)
    app.validate_gemini_api_key()
    
    # Setup right-click menu
    popup_handler = create_popup_menu(root, app)
    root.bind("<Button-3>", popup_handler)
    
    def start_thread_delayed():
        app.start_screenshot_thread()
    
    root.after(100, start_thread_delayed)
    print_help()
    
    root.mainloop()


def print_help():
    """Print help information and keyboard shortcuts"""
    print("\n" + "="*60)
    print("KEYBOARD SHORTCUTS:")
    print("  Shift + A           Toggle window visibility")
    print("  Ctrl + Shift        Take immediate screenshot")
    print("  Ctrl + Space        Pause/Resume monitoring")
    print("  Shift + R           Reload application")
    print("  Shift + Ctrl + X    Exit application")
    print("")
    print("FILES:")
    print("  • context.txt       Add example questions/answers")
    print("  • screenshots/      Saved screenshot folder")
    print("  • .env              API_KEY=your_gemini_key")
    print("")
    print("STATUS INDICATORS:")
    print("  • Number (12-00)    Countdown to next screenshot")
    print("  • Letter (A,B,C)    AI's answer choice")
    print("  • X                 No question detected")
    print("  • WAIT...           Processing screenshot")
    print("  • Paused            Monitoring paused")
    print("="*60)
    
if __name__ == "__main__":
    main()