package signing

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"net/url"
	"strings"

	"github.com/google/uuid"
)

// Signer generates HMAC-SHA256 request signatures matching the Idealista mobile
// app's signing scheme: seed + METHOD + sortedEncode(queryParams) + sortedEncode(bodyParams).
type Signer struct {
	secret string
}

// New creates a Signer using the provided raw signing secret. The raw secret is
// base64-encoded before use as the HMAC key.
func New(raw string) (*Signer, error) {
	if strings.TrimSpace(raw) == "" {
		return nil, fmt.Errorf("signing secret is required")
	}
	return &Signer{secret: base64.StdEncoding.EncodeToString([]byte(raw))}, nil
}

// Sign generates a seed UUID and computes an HMAC-SHA256 signature for the given
// HTTP method and parameters. Returns the seed and hex-encoded signature.
//
// The signature input is: seed + METHOD + sortedEncode(queryParams) + sortedEncode(bodyParams)
// Parameters use form encoding, matching the mobile API's signature verifier.
func (s *Signer) Sign(method string, queryParams, bodyParams url.Values) (seed, signature string, err error) {
	seed = uuid.New().String()
	input := seed + strings.ToUpper(method) + sortedEncode(queryParams) + sortedEncode(bodyParams)
	mac := hmac.New(sha256.New, []byte(s.secret))
	mac.Write([]byte(input))
	signature = hex.EncodeToString(mac.Sum(nil))
	return seed, signature, nil
}

// sortedEncode uses the same sorted form encoding as the HTTP query and body.
// In particular, spaces must be '+'; signing them as '%20' makes searches such
// as "Las Palmas" fail with HTTP 400 "Invalid request headers".
func sortedEncode(params url.Values) string {
	return params.Encode()
}
