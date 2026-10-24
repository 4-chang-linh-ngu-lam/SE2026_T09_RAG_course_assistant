export interface PersonalDataPort {
  download(requestId: string): Promise<{name: string; type: string; bytes: Uint8Array}>;
}
