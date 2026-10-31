export function KeyboardGuide(){
 const modifier=/Mac/.test(navigator.platform)?'⌘':'Ctrl';
 return <footer className="app-statusbar agent-statusbar" aria-label="Keyboard shortcuts">
  <span><kbd>←</kbd><kbd>→</kbd> frame <kbd>Space</kbd> play <kbd>F</kbd> fit</span>
  <span><kbd>J</kbd><kbd>K</kbd> intervention</span>
  <span><kbd>V</kbd> pan <kbd>P</kbd> pen <kbd>H</kbd> highlight <kbd>Esc</kbd> pan <kbd>{modifier} Z</kbd> undo</span>
 </footer>;
}
