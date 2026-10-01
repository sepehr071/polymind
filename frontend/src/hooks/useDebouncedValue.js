import { useEffect, useState } from 'react'

/**
 * Debounce a fast-changing value (typically a controlled search input).
 *
 * Bind the live value to your input so typing stays responsive, then drive
 * network/query work off the returned debounced value so it only settles
 * `delay` ms after the user stops typing.
 *
 *   const [search, setSearch] = useState('')
 *   const debouncedSearch = useDebouncedValue(search, 350)
 *
 * @param {*} value      The immediate value to debounce.
 * @param {number} delay Quiet period in ms before the value propagates.
 */
export default function useDebouncedValue(value, delay = 350) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}
