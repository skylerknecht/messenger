using System;
using System.Linq;
using System.Text;
using System.Security.Cryptography;


namespace MessengerClient
{
    internal class Crypto
    {
        private const int AesBlockByteSize = 128 / 8;
        private static readonly RandomNumberGenerator Random = RandomNumberGenerator.Create();

        public static byte[] Hash(string encryption_key)
        {
            using (SHA256 sha256 = SHA256.Create())
            {
                return sha256.ComputeHash(Encoding.ASCII.GetBytes(encryption_key));
            }
        }

        public static byte[] Encrypt(byte[] key, ArraySegment<byte> plainText)
        {
            byte[] plainTextBytes = plainText.Array;
            return Encrypt(key, plainTextBytes);
        }

        public static byte[] Encrypt(byte[] key, string plainText)
        {
            byte[] plainTextBytes = Encoding.UTF8.GetBytes(plainText);
            return Encrypt(key, plainTextBytes);
        }

        public static byte[] Encrypt(byte[] key, byte[] plainText)
        {
            using (var aes = Aes.Create())
            {

                byte[] iv = GenerateRandomBytes(AesBlockByteSize);

                using (var encryptor = aes.CreateEncryptor(key, iv))
                {
                    var cipherText = encryptor
                        .TransformFinalBlock(plainText, 0, plainText.Length);

                    var result = MergeArrays(iv, cipherText);
                    return result;
                }
            }
        }

        public static byte[] Decrypt(byte[] key, byte[] encryptedData)
        {
            using (var aes = Aes.Create())
            {
                var iv = encryptedData.Take(AesBlockByteSize).ToArray();
                var cipherText = encryptedData.Skip(AesBlockByteSize).ToArray();

                using (var encryptor = aes.CreateDecryptor(key, iv))
                {
                    return encryptor.TransformFinalBlock(cipherText, 0, cipherText.Length);
                }
            }
        }

        private static byte[] GenerateRandomBytes(int numberOfBytes)
        {
            var randomBytes = new byte[numberOfBytes];
            Random.GetBytes(randomBytes);
            return randomBytes;
        }

        private static byte[] MergeArrays(params byte[][] arrays)
        {
            var merged = new byte[arrays.Sum(a => a.Length)];
            var mergeIndex = 0;
            for (int i = 0; i < arrays.GetLength(0); i++)
            {
                arrays[i].CopyTo(merged, mergeIndex);
                mergeIndex += arrays[i].Length;
            }
            return merged;
        }
    }
}