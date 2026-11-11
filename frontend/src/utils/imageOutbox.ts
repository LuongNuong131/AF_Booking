const databaseName = 'booking-image-outbox-v1'
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1)
    request.onupgradeneeded = () => request.result.createObjectStore('images')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('Cannot store selected images'))
  })
}
async function access<T>(key: string, action: 'get' | 'put' | 'delete', files?: File[]): Promise<T> {
  const db = await database()
  try {
    return await new Promise<T>((resolve, reject) => {
      const transaction = db.transaction('images', action === 'get' ? 'readonly' : 'readwrite')
      const store = transaction.objectStore('images')
      const request = action === 'put' ? store.put(files, key) : action === 'delete' ? store.delete(key) : store.get(key)
      transaction.oncomplete = () => resolve(request.result as T)
      transaction.onerror = () => reject(new Error('Cannot store selected images'))
      transaction.onabort = () => reject(new Error('Cannot store selected images'))
    })
  } finally { db.close() }
}
export const imageBatchKey = (user: number, requestId: string) => `${user}/${requestId}`
export const storeImages = (key: string, files: File[]) => access<void>(key, 'put', files)
export const loadImages = (key: string) => access<File[] | undefined>(key, 'get')
export const removeImages = (key: string) => access<void>(key, 'delete')
