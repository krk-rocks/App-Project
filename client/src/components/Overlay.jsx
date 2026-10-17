import { createPortal } from 'react-dom'
import { motion, useIsPresent } from 'framer-motion'

/* Sheets and dialogs live in <body>: the page panels sit inside stacking contexts that would otherwise
   paint over them. Clicking the dimmed background closes the sheet.

   While a sheet is animating out it must not catch clicks. framer-motion removes it once its exit animation
   finishes, but that cleanup runs on animation frames, which a backgrounded tab pauses, so a closing sheet
   could linger invisibly and swallow every click on the page. useIsPresent turns it click-through the moment
   it starts closing. */
export default function Overlay({ children, onClose }) {
  const present = useIsPresent()
  return createPortal(
    <motion.div className="sheet-back" style={{ pointerEvents: present ? 'auto' : 'none' }}
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
      {children}
    </motion.div>,
    document.body,
  )
}
